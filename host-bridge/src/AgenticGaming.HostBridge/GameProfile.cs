using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AgenticGaming.HostBridge;

public sealed class GameProfile
{
    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    [JsonPropertyName("display_name")]
    public string DisplayName { get; init; } = string.Empty;

    [JsonPropertyName("title_contains")]
    public string[] TitleContains { get; init; } = [];

    [JsonPropertyName("process_names")]
    public string[] ProcessNames { get; init; } = [];

    public bool Matches(WindowInfo window)
    {
        var titleMatches = TitleContains.Length == 0 ||
            TitleContains.Any(value => window.Title.Contains(value, StringComparison.OrdinalIgnoreCase));
        var processMatches = ProcessNames.Length == 0 ||
            ProcessNames.Any(value => string.Equals(
                NormalizeProcessName(value),
                NormalizeProcessName(window.ProcessName),
                StringComparison.OrdinalIgnoreCase));
        return titleMatches && processMatches;
    }

    private static string NormalizeProcessName(string value)
    {
        return Path.GetFileNameWithoutExtension(value.Trim());
    }
}

public sealed class GameProfileCatalog
{
    private readonly IReadOnlyList<GameProfile> _profiles;

    private GameProfileCatalog(IReadOnlyList<GameProfile> profiles)
    {
        _profiles = profiles;
    }

    public IReadOnlyList<GameProfile> Profiles => _profiles;

    public static GameProfileCatalog Load(string directory)
    {
        if (!Directory.Exists(directory))
        {
            throw new DirectoryNotFoundException($"Game profile directory was not found: {directory}");
        }

        var profiles = Directory.EnumerateFiles(directory, "*.json", SearchOption.TopDirectoryOnly)
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Select(path => JsonSerializer.Deserialize<GameProfile>(File.ReadAllText(path), BridgeJson.Options)
                ?? throw new InvalidDataException($"Profile file is empty: {path}"))
            .Where(profile => !string.IsNullOrWhiteSpace(profile.Id))
            .ToArray();

        if (profiles.Length == 0)
        {
            throw new InvalidDataException($"No valid game profiles were found in: {directory}");
        }

        return new GameProfileCatalog(profiles);
    }
}

public sealed record WindowSelection(
    [property: JsonPropertyName("profile_id")] string ProfileId,
    [property: JsonPropertyName("window_handle")] long WindowHandle,
    [property: JsonPropertyName("process_id")] int ProcessId,
    [property: JsonPropertyName("process_name")] string ProcessName,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("bounds")] WindowBounds Bounds);
