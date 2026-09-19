using System.Text.Json;
using System.Text.Json.Serialization;

namespace AgenticGaming.HostBridge;

public sealed record BridgeHelloMessage(
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("protocol_version")] string ProtocolVersion,
    [property: JsonPropertyName("client_id")] string ClientId,
    [property: JsonPropertyName("capabilities")] string[] Capabilities,
    [property: JsonPropertyName("dry_run")] bool DryRun,
    [property: JsonPropertyName("profile_id")] string? ProfileId,
    [property: JsonPropertyName("safe_capture")] bool SafeCapture,
    [property: JsonPropertyName("run_id")] string? RunId,
    [property: JsonPropertyName("audio")] AudioStreamDescriptor? Audio);

public sealed record AudioStreamDescriptor(
    [property: JsonPropertyName("stream_id")] string StreamId,
    [property: JsonPropertyName("mode")] string Mode,
    [property: JsonPropertyName("device_id")] string? DeviceId,
    [property: JsonPropertyName("device_name")] string? DeviceName,
    [property: JsonPropertyName("source_process_id")] int? SourceProcessId,
    [property: JsonPropertyName("source_process_name")] string? SourceProcessName,
    [property: JsonPropertyName("sample_rate")] int SampleRate,
    [property: JsonPropertyName("channels")] int Channels,
    [property: JsonPropertyName("sample_format")] string SampleFormat,
    [property: JsonPropertyName("chunk_duration_ms")] int ChunkDurationMs);

public sealed record BridgeFrameMessage(
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("frame_id")] string FrameId,
    [property: JsonPropertyName("captured_at_ns")] long CapturedAtNs,
    [property: JsonPropertyName("width")] int Width,
    [property: JsonPropertyName("height")] int Height,
    [property: JsonPropertyName("encoding")] string Encoding,
    [property: JsonPropertyName("data_base64")] string DataBase64,
    [property: JsonPropertyName("source_window_title")] string SourceWindowTitle,
    [property: JsonPropertyName("source_process_id")] int SourceProcessId);

public sealed record BridgeHeartbeatMessage(
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("sent_at_ns")] long SentAtNs);

public sealed record BridgeAudioChunkMessage(
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("stream_id")] string StreamId,
    [property: JsonPropertyName("chunk_id")] string ChunkId,
    [property: JsonPropertyName("sequence")] long Sequence,
    [property: JsonPropertyName("started_at_ns")] long StartedAtNs,
    [property: JsonPropertyName("duration_ns")] long DurationNs,
    [property: JsonPropertyName("sample_rate")] int SampleRate,
    [property: JsonPropertyName("channels")] int Channels,
    [property: JsonPropertyName("sample_format")] string SampleFormat,
    [property: JsonPropertyName("frame_count")] int FrameCount,
    [property: JsonPropertyName("data_base64")] string DataBase64,
    [property: JsonPropertyName("device_id")] string? DeviceId,
    [property: JsonPropertyName("device_name")] string? DeviceName,
    [property: JsonPropertyName("source_process_id")] int? SourceProcessId,
    [property: JsonPropertyName("source_process_name")] string? SourceProcessName,
    [property: JsonPropertyName("capture_packets_dropped")] long CapturePacketsDropped);

public sealed record CapturedFrame(
    string FrameId,
    long CapturedAtNs,
    int Width,
    int Height,
    byte[] PngBytes,
    CaptureRegion Region);

public sealed record CapturedAudioChunk(
    string StreamId,
    string ChunkId,
    long Sequence,
    long StartedAtNs,
    long DurationNs,
    int SampleRate,
    int Channels,
    string SampleFormat,
    int FrameCount,
    byte[] PcmBytes,
    string? DeviceId,
    string? DeviceName,
    int? SourceProcessId,
    string? SourceProcessName,
    long CapturePacketsDropped);

public static class BridgeJson
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };
}
