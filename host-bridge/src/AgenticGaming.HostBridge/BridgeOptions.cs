using System.IO;

namespace AgenticGaming.HostBridge;

public sealed record BridgeOptions(
    Uri CoreWebSocketEndpoint,
    string Token,
    int CaptureIntervalMs,
    int MaxCaptureWidth,
    int MaxCaptureHeight,
    string ProfilesDirectory,
    string SelectionPath,
    bool DryRun,
    bool UseDesktopCapture,
    bool SafeCapture,
    string LogPath,
    string PreviewPath,
    bool AudioEnabled,
    string AudioMode,
    string? AudioDeviceId,
    int AudioChunkMs,
    int AudioBufferMs,
    string AudioLatestPath,
    string? RunId,
    bool ListAudioDevices)
{
    public static BridgeOptions FromEnvironment(string[] args)
    {
        var endpoint = Environment.GetEnvironmentVariable("AGENTIC_CORE_WS")
            ?? "ws://localhost:8000/ws/host-bridge";
        var token = Environment.GetEnvironmentVariable("HOST_BRIDGE_TOKEN")
            ?? "dev-only-change-me";
        var interval = ReadPositiveInt("BRIDGE_CAPTURE_INTERVAL_MS", 500);
        var maxWidth = ReadPositiveInt("BRIDGE_MAX_CAPTURE_WIDTH", 1280);
        var maxHeight = ReadPositiveInt("BRIDGE_MAX_CAPTURE_HEIGHT", 720);
        var repositoryRoot = PathLocator.FindRepositoryRoot();
        var profilesDirectory = Environment.GetEnvironmentVariable("BRIDGE_PROFILES_DIR")
            ?? Path.Combine(repositoryRoot, "host-bridge", "profiles");
        var selectionPath = Environment.GetEnvironmentVariable("BRIDGE_SELECTION_PATH")
            ?? Path.Combine(repositoryRoot, "data", "bridge", "selection.json");
        var dryRun = ReadBoolean("BRIDGE_DRY_RUN", true);
        var logPath = Environment.GetEnvironmentVariable("BRIDGE_LOG_PATH")
            ?? Path.Combine(repositoryRoot, "data", "logs", "host-bridge.jsonl");
        var previewPath = Environment.GetEnvironmentVariable("BRIDGE_PREVIEW_PATH")
            ?? Path.Combine(repositoryRoot, "data", "bridge", "preview.png");
        var audioEnabled = ReadBoolean("BRIDGE_AUDIO_ENABLED", true) &&
            !args.Any(argument => argument.Equals("--no-audio", StringComparison.OrdinalIgnoreCase));
        var audioMode = ReadOption(args, "--audio-mode") ??
            Environment.GetEnvironmentVariable("BRIDGE_AUDIO_MODE") ?? "process_loopback";
        var audioDeviceId = ReadOption(args, "--audio-device") ??
            Environment.GetEnvironmentVariable("BRIDGE_AUDIO_DEVICE_ID");
        var audioChunkMs = ReadPositiveInt("BRIDGE_AUDIO_CHUNK_MS", 40);
        var audioBufferMs = ReadPositiveInt("BRIDGE_AUDIO_BUFFER_MS", 100);
        var audioLatestPath = Environment.GetEnvironmentVariable("BRIDGE_AUDIO_LATEST_PATH")
            ?? Path.Combine(repositoryRoot, "data", "bridge", "host-latest-audio.pcm");
        var runId = Environment.GetEnvironmentVariable("BRIDGE_RUN_ID");

        if (args.Any(argument => argument.Equals("--live-input", StringComparison.OrdinalIgnoreCase)))
        {
            dryRun = false;
        }

        var useDesktopCapture = args.Any(argument =>
            argument.Equals("--screen", StringComparison.OrdinalIgnoreCase));
        var safeCapture = useDesktopCapture ||
            ReadBoolean("BRIDGE_SAFE_CAPTURE", false) ||
            args.Any(argument => argument.Equals("--safe-capture", StringComparison.OrdinalIgnoreCase));
        var listAudioDevices = args.Any(argument =>
            argument.Equals("--list-audio-devices", StringComparison.OrdinalIgnoreCase));

        if (!audioMode.Equals("process_loopback", StringComparison.OrdinalIgnoreCase) &&
            !audioMode.Equals("system_loopback", StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException(
                "BRIDGE_AUDIO_MODE deve ser process_loopback ou system_loopback.");
        }

        return new BridgeOptions(
            new Uri(endpoint),
            token,
            interval,
            maxWidth,
            maxHeight,
            profilesDirectory,
            selectionPath,
            dryRun,
            useDesktopCapture,
            safeCapture,
            logPath,
            previewPath,
            audioEnabled,
            audioMode.ToLowerInvariant(),
            audioDeviceId,
            audioChunkMs,
            audioBufferMs,
            audioLatestPath,
            runId,
            listAudioDevices);
    }

    private static int ReadPositiveInt(string name, int fallback)
    {
        return int.TryParse(Environment.GetEnvironmentVariable(name), out var value) && value > 0
            ? value
            : fallback;
    }

    private static bool ReadBoolean(string name, bool fallback)
    {
        return bool.TryParse(Environment.GetEnvironmentVariable(name), out var value)
            ? value
            : fallback;
    }

    private static string? ReadOption(string[] args, string option)
    {
        for (var index = 0; index < args.Length - 1; index++)
        {
            if (args[index].Equals(option, StringComparison.OrdinalIgnoreCase))
            {
                return args[index + 1];
            }
        }

        return null;
    }
}
