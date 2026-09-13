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
    [property: JsonPropertyName("safe_capture")] bool SafeCapture);

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

public sealed record CapturedFrame(
    string FrameId,
    long CapturedAtNs,
    int Width,
    int Height,
    byte[] PngBytes,
    CaptureRegion Region);

public static class BridgeJson
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };
}
