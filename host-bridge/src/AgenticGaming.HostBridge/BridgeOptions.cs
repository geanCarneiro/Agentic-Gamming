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
    string PreviewPath)
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

        if (args.Any(argument => argument.Equals("--live-input", StringComparison.OrdinalIgnoreCase)))
        {
            dryRun = false;
        }

        var useDesktopCapture = args.Any(argument =>
            argument.Equals("--screen", StringComparison.OrdinalIgnoreCase));
        var safeCapture = useDesktopCapture ||
            ReadBoolean("BRIDGE_SAFE_CAPTURE", false) ||
            args.Any(argument => argument.Equals("--safe-capture", StringComparison.OrdinalIgnoreCase));

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
            previewPath);
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
}
