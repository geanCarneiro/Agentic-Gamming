using System.Net.WebSockets;
using System.IO;
using System.Text;
using System.Text.Json;

namespace AgenticGaming.HostBridge;

public sealed class CoreWebSocketClient
{
    private readonly BridgeOptions _options;
    private readonly JsonLineLogger _logger;
    private readonly OverlayHost? _overlay;
    private readonly string? _profileId;
    private readonly SemaphoreSlim _sendGate = new(1, 1);
    private readonly string _clientId = $"host-{Environment.MachineName}-{Guid.NewGuid():N}";

    public CoreWebSocketClient(
        BridgeOptions options,
        JsonLineLogger logger,
        OverlayHost? overlay = null,
        string? profileId = null)
    {
        _options = options;
        _logger = logger;
        _overlay = overlay;
        _profileId = profileId;
    }

    public async Task RunAsync(
        DesktopScreenCapture capture,
        AudioCapture? audioCapture,
        CancellationToken cancellationToken)
    {
        using var socket = new ClientWebSocket();
        socket.Options.SetRequestHeader("X-Bridge-Token", _options.Token);

        await _logger.WriteAsync("transport.connecting", new
        {
            endpoint = _options.CoreWebSocketEndpoint,
            client_id = _clientId,
        }, cancellationToken);
        await socket.ConnectAsync(_options.CoreWebSocketEndpoint, cancellationToken);
        await _logger.WriteAsync("transport.connected", new { client_id = _clientId }, cancellationToken);

        if (audioCapture is not null)
        {
            await audioCapture.InitializeAsync(cancellationToken);
        }

        await SendAsync(socket, new BridgeHelloMessage(
            "hello",
            "beta-3",
            _clientId,
            BuildCapabilities(audioCapture is not null),
            _options.DryRun,
            _profileId,
            _options.SafeCapture,
            _options.RunId,
            audioCapture?.Descriptor), cancellationToken);

        using var linkedCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var receiver = ReceiveLoopAsync(socket, linkedCancellation.Token);
        Task? audioTask = null;

        if (audioCapture is not null)
        {
            audioTask = RunAudioAsync(socket, audioCapture, linkedCancellation.Token);
            _ = audioTask.ContinueWith(
                _ => linkedCancellation.Cancel(),
                CancellationToken.None,
                TaskContinuationOptions.ExecuteSynchronously,
                TaskScheduler.Default);
        }

        try
        {
            while (!linkedCancellation.IsCancellationRequested)
            {
                if (receiver.IsCompleted)
                {
                    await receiver;
                    break;
                }

                if (audioTask is { IsCompleted: true })
                {
                    await audioTask;
                    break;
                }

                if (_overlay is not null && _options.SafeCapture)
                {
                    await _overlay.SetVisibleAsync(false, linkedCancellation.Token);
                }

                var frame = await capture.CaptureAsync(linkedCancellation.Token);
                if (_overlay is not null)
                {
                    await _overlay.UpdateAsync(frame, linkedCancellation.Token);
                }

                var message = new BridgeFrameMessage(
                    "frame",
                    frame.FrameId,
                    frame.CapturedAtNs,
                    frame.Width,
                    frame.Height,
                    "png",
                    Convert.ToBase64String(frame.PngBytes),
                    frame.Region.Title,
                    frame.Region.ProcessId);
                await SendAsync(socket, message, linkedCancellation.Token);

                await Task.Delay(_options.CaptureIntervalMs, linkedCancellation.Token);
            }
        }
        finally
        {
            linkedCancellation.Cancel();
            try
            {
                await receiver;
            }
            catch (OperationCanceledException) when (linkedCancellation.IsCancellationRequested)
            {
                // Normal shutdown.
            }

            if (audioTask is not null)
            {
                try
                {
                    await audioTask;
                }
                catch (OperationCanceledException) when (linkedCancellation.IsCancellationRequested)
                {
                    // Normal shutdown.
                }
            }

            if (socket.State is WebSocketState.Open or WebSocketState.CloseReceived)
            {
                await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "bridge stopping", CancellationToken.None);
            }
        }
    }

    private async Task RunAudioAsync(
        ClientWebSocket socket,
        AudioCapture audioCapture,
        CancellationToken cancellationToken)
    {
        await audioCapture.RunAsync(async chunk =>
        {
            await PersistLatestAudioAsync(chunk, cancellationToken);
            await SendAsync(socket, new BridgeAudioChunkMessage(
                "audio_chunk",
                chunk.StreamId,
                chunk.ChunkId,
                chunk.Sequence,
                chunk.StartedAtNs,
                chunk.DurationNs,
                chunk.SampleRate,
                chunk.Channels,
                chunk.SampleFormat,
                chunk.FrameCount,
                Convert.ToBase64String(chunk.PcmBytes),
                chunk.DeviceId,
                chunk.DeviceName,
                chunk.SourceProcessId,
                chunk.SourceProcessName,
                chunk.CapturePacketsDropped), cancellationToken);

            if (chunk.Sequence == 1 || chunk.Sequence % 25 == 0)
            {
                await _logger.WriteAsync("audio.chunk_sent", new
                {
                    stream_id = chunk.StreamId,
                    chunk_id = chunk.ChunkId,
                    sequence = chunk.Sequence,
                    started_at_ns = chunk.StartedAtNs,
                    duration_ns = chunk.DurationNs,
                    bytes = chunk.PcmBytes.Length,
                    dropped_packets = audioCapture.DroppedPackets,
                }, cancellationToken);
            }
        }, cancellationToken);
    }

    private async Task PersistLatestAudioAsync(
        CapturedAudioChunk chunk,
        CancellationToken cancellationToken)
    {
        var path = Path.GetFullPath(_options.AudioLatestPath);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await File.WriteAllBytesAsync(path, chunk.PcmBytes, cancellationToken);

        var metadataPath = Path.ChangeExtension(path, ".json");
        var metadata = new
        {
            stream_id = chunk.StreamId,
            chunk_id = chunk.ChunkId,
            sequence = chunk.Sequence,
            started_at_ns = chunk.StartedAtNs,
            duration_ns = chunk.DurationNs,
            sample_rate = chunk.SampleRate,
            channels = chunk.Channels,
            sample_format = chunk.SampleFormat,
            frame_count = chunk.FrameCount,
            bytes = chunk.PcmBytes.Length,
            device_id = chunk.DeviceId,
            device_name = chunk.DeviceName,
            source_process_id = chunk.SourceProcessId,
            source_process_name = chunk.SourceProcessName,
        };
        await File.WriteAllTextAsync(
            metadataPath,
            JsonSerializer.Serialize(metadata, BridgeJson.Options) + Environment.NewLine,
            cancellationToken);
    }

    private async Task ReceiveLoopAsync(ClientWebSocket socket, CancellationToken cancellationToken)
    {
        var buffer = new byte[64 * 1024];
        using var message = new MemoryStream();

        while (!cancellationToken.IsCancellationRequested && socket.State == WebSocketState.Open)
        {
            message.SetLength(0);
            WebSocketReceiveResult result;
            do
            {
                result = await socket.ReceiveAsync(buffer, cancellationToken);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    await _logger.WriteAsync("transport.closed_by_core", new
                    {
                        status = result.CloseStatus?.ToString(),
                        description = result.CloseStatusDescription,
                    }, cancellationToken);
                    return;
                }

                await message.WriteAsync(buffer.AsMemory(0, result.Count), cancellationToken);
            }
            while (!result.EndOfMessage);

            var text = Encoding.UTF8.GetString(message.ToArray());
            await _logger.WriteAsync("transport.message_received", new { message = text }, cancellationToken);
        }
    }

    private static string[] BuildCapabilities(bool audioEnabled)
    {
        return audioEnabled
            ? ["screen_capture", "preview_frame", "basic_overlay", "audio_pcm", "latest_audio_chunk"]
            : ["screen_capture", "preview_frame", "basic_overlay"];
    }

    private async Task SendAsync(ClientWebSocket socket, object message, CancellationToken cancellationToken)
    {
        var json = JsonSerializer.Serialize(message, BridgeJson.Options);
        var bytes = Encoding.UTF8.GetBytes(json);
        await _sendGate.WaitAsync(cancellationToken);
        try
        {
            await socket.SendAsync(bytes, WebSocketMessageType.Text, true, cancellationToken);
        }
        finally
        {
            _sendGate.Release();
        }
    }
}
