using System.Text.Json;
using System.IO;
using System.Threading;

namespace AgenticGaming.HostBridge;

public sealed class JsonLineLogger
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly string _path;
    private readonly SemaphoreSlim _gate = new(1, 1);

    public JsonLineLogger(string path)
    {
        _path = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(_path)!);
    }

    public async Task WriteAsync(string eventType, object payload, CancellationToken cancellationToken = default)
    {
        var entry = new
        {
            timestamp = DateTimeOffset.UtcNow,
            event_type = eventType,
            payload,
        };
        var line = JsonSerializer.Serialize(entry, JsonOptions) + Environment.NewLine;

        await _gate.WaitAsync(cancellationToken);
        try
        {
            await File.AppendAllTextAsync(_path, line, cancellationToken);
        }
        finally
        {
            _gate.Release();
        }

        Console.WriteLine(line.TrimEnd());
    }
}
