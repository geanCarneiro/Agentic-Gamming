using System.IO;

namespace AgenticGaming.HostBridge;

public static class PathLocator
{
    public static string FindRepositoryRoot()
    {
        foreach (var start in new[]
                 {
                     new DirectoryInfo(Directory.GetCurrentDirectory()),
                     new DirectoryInfo(AppContext.BaseDirectory),
                 })
        {
            for (var directory = start; directory is not null; directory = directory.Parent)
            {
                if (File.Exists(Path.Combine(directory.FullName, "compose.yaml")) &&
                    Directory.Exists(Path.Combine(directory.FullName, "host-bridge")))
                {
                    return directory.FullName;
                }
            }
        }

        return Directory.GetCurrentDirectory();
    }
}
