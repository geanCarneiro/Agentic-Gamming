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

    public async Task RunAsync(DesktopScreenCapture capture, CancellationToken cancellationToken)
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

        await SendAsync(socket, new BridgeHelloMessage(
            "hello",
            "1.0",
            _clientId,
            ["screen_capture", "preview_frame", "basic_overlay", "keyboard_mouse_input"],
            _options.DryRun,
            _profileId,
            _options.SafeCapture), cancellationToken);

        using var linkedCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var receiver = ReceiveLoopAsync(socket, linkedCancellation.Token);

        try
        {
            while (!linkedCancellation.IsCancellationRequested)
            {
                if (receiver.IsCompleted)
                {
                    await receiver;
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

            if (socket.State is WebSocketState.Open or WebSocketState.CloseReceived)
            {
                await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "bridge stopping", CancellationToken.None);
            }
        }
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

    private static async Task SendAsync(ClientWebSocket socket, object message, CancellationToken cancellationToken)
    {
        var json = JsonSerializer.Serialize(message, BridgeJson.Options);
        var bytes = Encoding.UTF8.GetBytes(json);
        await socket.SendAsync(bytes, WebSocketMessageType.Text, true, cancellationToken);
    }
}
