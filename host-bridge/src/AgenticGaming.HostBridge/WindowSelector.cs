using System.IO;
using System.Linq;
using System.Text.Json;

namespace AgenticGaming.HostBridge;

public sealed class WindowSelector
{
    private readonly WindowCatalog _catalog;
    private readonly JsonLineLogger _logger;

    public WindowSelector(WindowCatalog catalog, JsonLineLogger logger)
    {
        _catalog = catalog;
        _logger = logger;
    }

    public async Task<WindowSelection?> SelectAsync(
        GameProfileCatalog profileCatalog,
        string selectionPath,
        CancellationToken cancellationToken)
    {
        Console.WriteLine("=== Agentic Gaming Host Bridge ===");
        Console.WriteLine("Selecione o Game Profile e a janela do jogo.");
        Console.WriteLine();

        var profile = SelectProfile(profileCatalog.Profiles);
        if (profile is null)
        {
            return null;
        }

        var allWindows = _catalog.GetVisibleWindows();
        var matchingWindows = allWindows.Where(profile.Matches).ToArray();
        var windows = matchingWindows.Length > 0 ? matchingWindows : allWindows.ToArray();

        if (matchingWindows.Length == 0)
        {
            Console.WriteLine("Nenhuma janela correspondeu ao perfil; exibindo todas as janelas visíveis.");
        }

        if (windows.Length == 0)
        {
            Console.WriteLine("Nenhuma janela visível foi encontrada.");
            return null;
        }

        Console.WriteLine();
        Console.WriteLine($"Janelas candidatas para '{profile.DisplayName}':");
        for (var index = 0; index < windows.Length; index++)
        {
            var window = windows[index];
            Console.WriteLine(
                $"[{index + 1}] {window.Title} | {window.ProcessName} (PID {window.ProcessId}) | " +
                $"{window.Bounds.Width}x{window.Bounds.Height}");
        }

        var selectedIndex = ReadIndex("Janela [1]: ", windows.Length, 0);
        if (selectedIndex is null)
        {
            return null;
        }

        var selected = windows[selectedIndex.Value];
        var selection = new WindowSelection(
            profile.Id,
            selected.HandleValue,
            selected.ProcessId,
            selected.ProcessName,
            selected.Title,
            selected.Bounds);

        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(selectionPath))!);
        var json = JsonSerializer.Serialize(selection, BridgeJson.Options);
        await File.WriteAllTextAsync(selectionPath, json + Environment.NewLine, cancellationToken);
        await _logger.WriteAsync("window.selected", new
        {
            profile_id = selection.ProfileId,
            window_handle = selection.WindowHandle,
            process_id = selection.ProcessId,
            process_name = selection.ProcessName,
            title = selection.Title,
            selection_path = Path.GetFullPath(selectionPath),
        }, cancellationToken);

        Console.WriteLine($"Janela selecionada: {selection.Title}");
        Console.WriteLine($"Seleção salva em: {Path.GetFullPath(selectionPath)}");
        return selection;
    }

    private static GameProfile? SelectProfile(IReadOnlyList<GameProfile> profiles)
    {
        for (var index = 0; index < profiles.Count; index++)
        {
            Console.WriteLine($"[{index + 1}] {profiles[index].DisplayName} ({profiles[index].Id})");
        }

        var selectedIndex = ReadIndex("Game Profile [1]: ", profiles.Count, 0);
        return selectedIndex is null ? null : profiles[selectedIndex.Value];
    }

    private static int? ReadIndex(string prompt, int count, int defaultIndex)
    {
        while (true)
        {
            Console.Write(prompt);
            var input = Console.ReadLine();
            if (string.IsNullOrWhiteSpace(input))
            {
                return defaultIndex;
            }

            if (int.TryParse(input, out var value) && value >= 1 && value <= count)
            {
                return value - 1;
            }

            Console.WriteLine("Opção inválida.");
        }
    }
}
