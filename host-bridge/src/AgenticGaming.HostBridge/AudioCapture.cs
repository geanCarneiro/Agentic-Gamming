using System.Threading.Channels;
using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace AgenticGaming.HostBridge;

public sealed class AudioCapture : IAsyncDisposable
{
    private sealed record RawAudioPacket(byte[] Data, long CapturedAtNs);

    private readonly BridgeOptions _options;
    private readonly JsonLineLogger _logger;
    private readonly int? _sourceProcessId;
    private readonly string? _sourceProcessName;
    private readonly Channel<RawAudioPacket> _packets = Channel.CreateBounded<RawAudioPacket>(
        new BoundedChannelOptions(128)
        {
            FullMode = BoundedChannelFullMode.Wait,
            SingleReader = true,
            SingleWriter = false,
        });

    private WasapiRecorder? _recorder;
    private NAudio.CoreAudioApi.MMDevice? _selectedDevice;
    private long _droppedPackets;
    private long _sequence;
    private string _streamId = $"audio-{Guid.NewGuid():N}";

    public AudioCapture(
        BridgeOptions options,
        JsonLineLogger logger,
        int? sourceProcessId,
        string? sourceProcessName)
    {
        _options = options;
        _logger = logger;
        _sourceProcessId = sourceProcessId;
        _sourceProcessName = sourceProcessName;
    }

    public AudioStreamDescriptor? Descriptor { get; private set; }

    public long DroppedPackets => Interlocked.Read(ref _droppedPackets);

    public async Task InitializeAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        if (_options.AudioMode == "process_loopback")
        {
            if (!_sourceProcessId.HasValue || _sourceProcessId <= 0)
            {
                throw new InvalidOperationException(
                    "Process loopback exige uma janela selecionada com PID válido.");
            }

            var builder = new WasapiRecorderBuilder()
                .WithProcessLoopback((uint)_sourceProcessId.Value)
                .WithFormat(WaveFormat.CreateIeeeFloatWaveFormat(44100, 2))
                .WithBufferLength(_options.AudioBufferMs);
            _recorder = await builder.BuildAsync();
        }
        else
        {
            var builder = new WasapiRecorderBuilder()
                .WithLoopbackCapture()
                .WithBufferLength(_options.AudioBufferMs);

            if (!string.IsNullOrWhiteSpace(_options.AudioDeviceId))
            {
                _selectedDevice = AudioDeviceCatalog.FindRenderDevice(_options.AudioDeviceId);
                if (_selectedDevice is null)
                {
                    throw new InvalidOperationException(
                        $"Dispositivo de áudio não encontrado ou inativo: {_options.AudioDeviceId}");
                }

                builder.WithDevice(_selectedDevice);
            }

            _recorder = await builder.BuildAsync();
        }

        var format = _recorder.WaveFormat;
        Descriptor = new AudioStreamDescriptor(
            _streamId,
            _options.AudioMode,
            _selectedDevice?.ID,
            _selectedDevice?.FriendlyName,
            _sourceProcessId,
            _sourceProcessName,
            format.SampleRate,
            format.Channels,
            ToSampleFormat(format),
            _options.AudioChunkMs);

        await _logger.WriteAsync("audio.capture_initialized", new
        {
            stream_id = _streamId,
            mode = _options.AudioMode,
            device_id = _selectedDevice?.ID,
            device_name = _selectedDevice?.FriendlyName,
            source_process_id = _sourceProcessId,
            source_process_name = _sourceProcessName,
            sample_rate = format.SampleRate,
            channels = format.Channels,
            sample_format = Descriptor.SampleFormat,
            chunk_duration_ms = _options.AudioChunkMs,
        }, cancellationToken);
    }

    public async Task RunAsync(
        Func<CapturedAudioChunk, Task> onChunk,
        CancellationToken cancellationToken)
    {
        if (_recorder is null || Descriptor is null)
        {
            throw new InvalidOperationException("AudioCapture.InitializeAsync deve ser chamado antes.");
        }

        var recorder = _recorder;
        recorder.DataAvailable += OnDataAvailable;
        recorder.RecordingStopped += OnRecordingStopped;

        try
        {
            recorder.StartRecording();
            await ConsumePacketsAsync(onChunk, cancellationToken);
        }
        finally
        {
            recorder.DataAvailable -= OnDataAvailable;
            recorder.RecordingStopped -= OnRecordingStopped;
            recorder.StopRecording();
            _packets.Writer.TryComplete();
        }
    }

    private void OnDataAvailable(
        ReadOnlySpan<byte> buffer,
        AudioClientBufferFlags _,
        long __,
        long ___)
    {
        var packet = new RawAudioPacket(
            buffer.ToArray(),
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() * 1_000_000);
        if (!_packets.Writer.TryWrite(packet))
        {
            Interlocked.Increment(ref _droppedPackets);
        }
    }

    private void OnRecordingStopped(object? _, StoppedEventArgs eventArgs)
    {
        if (eventArgs.Exception is not null)
        {
            _ = _logger.WriteAsync("audio.capture_stopped_with_error", new
            {
                exception = eventArgs.Exception.GetType().FullName,
                message = eventArgs.Exception.Message,
            });
        }

        _packets.Writer.TryComplete(eventArgs.Exception);
    }

    private async Task ConsumePacketsAsync(
        Func<CapturedAudioChunk, Task> onChunk,
        CancellationToken cancellationToken)
    {
        var descriptor = Descriptor!;
        var bytesPerFrame = descriptor.Channels * BytesPerSample(descriptor.SampleFormat);
        var framesPerChunk = Math.Max(1, (int)Math.Round(
            descriptor.SampleRate * (_options.AudioChunkMs / 1000d)));
        var chunkBytes = framesPerChunk * bytesPerFrame;
        var accumulator = new byte[chunkBytes];
        var accumulatedBytes = 0;
        long? nextStartedAtNs = null;

        await foreach (var packet in _packets.Reader.ReadAllAsync(cancellationToken))
        {
            var offset = 0;
            while (offset < packet.Data.Length)
            {
                nextStartedAtNs ??= packet.CapturedAtNs;
                var bytesToCopy = Math.Min(chunkBytes - accumulatedBytes, packet.Data.Length - offset);
                Buffer.BlockCopy(packet.Data, offset, accumulator, accumulatedBytes, bytesToCopy);
                accumulatedBytes += bytesToCopy;
                offset += bytesToCopy;

                if (accumulatedBytes < chunkBytes)
                {
                    continue;
                }

                var chunk = new CapturedAudioChunk(
                    descriptor.StreamId,
                    Guid.NewGuid().ToString("N"),
                    Interlocked.Increment(ref _sequence),
                    nextStartedAtNs!.Value,
                    _options.AudioChunkMs * 1_000_000L,
                    descriptor.SampleRate,
                    descriptor.Channels,
                    descriptor.SampleFormat,
                    framesPerChunk,
                    accumulator,
                    descriptor.DeviceId,
                    descriptor.DeviceName,
                    descriptor.SourceProcessId,
                    descriptor.SourceProcessName,
                    DroppedPackets);
                await onChunk(chunk);

                accumulator = new byte[chunkBytes];
                accumulatedBytes = 0;
                nextStartedAtNs += chunk.DurationNs;
            }
        }

        if (_droppedPackets > 0)
        {
            await _logger.WriteAsync("audio.capture_packets_dropped", new
            {
                dropped_packets = _droppedPackets,
            }, cancellationToken);
        }
    }

    private static int BytesPerSample(string sampleFormat)
    {
        return sampleFormat switch
        {
            "pcm_f32le" => 4,
            "pcm_s16le" => 2,
            _ => throw new InvalidOperationException($"Formato PCM não suportado: {sampleFormat}"),
        };
    }

    private static string ToSampleFormat(WaveFormat format)
    {
        return format.Encoding == WaveFormatEncoding.IeeeFloat && format.BitsPerSample == 32
            ? "pcm_f32le"
            : format.Encoding == WaveFormatEncoding.Pcm && format.BitsPerSample == 16
                ? "pcm_s16le"
                : throw new InvalidOperationException(
                    $"Formato PCM negociado não suportado: {format.Encoding}/{format.BitsPerSample}");
    }

    public async ValueTask DisposeAsync()
    {
        if (_recorder is not null)
        {
            await _recorder.DisposeAsync();
            _recorder = null;
        }

        _selectedDevice?.Dispose();
        _selectedDevice = null;
    }
}
