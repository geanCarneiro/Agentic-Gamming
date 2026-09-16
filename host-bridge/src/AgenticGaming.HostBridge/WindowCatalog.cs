using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json.Serialization;

namespace AgenticGaming.HostBridge;

public sealed record WindowBounds(
    [property: JsonPropertyName("left")] int Left,
    [property: JsonPropertyName("top")] int Top,
    [property: JsonPropertyName("width")] int Width,
    [property: JsonPropertyName("height")] int Height);

public sealed record WindowInfo(
    IntPtr Handle,
    int ProcessId,
    string ProcessName,
    string Title,
    WindowBounds Bounds)
{
    public long HandleValue => Handle.ToInt64();
}

public sealed record CaptureRegion(
    IntPtr WindowHandle,
    int ProcessId,
    string ProcessName,
    string Title,
    WindowBounds Bounds);

public sealed class WindowCatalog
{
    private delegate bool EnumWindowsCallback(IntPtr windowHandle, IntPtr lParam);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumWindows(EnumWindowsCallback callback, IntPtr lParam);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumDesktopWindows(
        IntPtr desktopHandle,
        EnumWindowsCallback callback,
        IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern IntPtr OpenInputDesktop(
        uint flags,
        [MarshalAs(UnmanagedType.Bool)] bool inherit,
        uint desiredAccess);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseDesktop(IntPtr desktopHandle);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr windowHandle, StringBuilder text, int maxCount);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr windowHandle, out uint processId);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindowVisible(IntPtr windowHandle);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindow(IntPtr windowHandle);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsIconic(IntPtr windowHandle);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetWindowRect(IntPtr windowHandle, out NativeRect rectangle);

    public IReadOnlyList<WindowInfo> GetVisibleWindows()
    {
        var windows = new List<WindowInfo>();
        var knownHandles = new HashSet<IntPtr>();

        void CollectWindow(IntPtr windowHandle)
        {
            if (!knownHandles.Add(windowHandle))
            {
                return;
            }

            if (!IsWindowVisible(windowHandle) || IsIconic(windowHandle))
            {
                return;
            }

            var title = GetTitle(windowHandle);
            if (string.IsNullOrWhiteSpace(title) || !GetWindowRect(windowHandle, out var nativeBounds))
            {
                return;
            }

            var bounds = ToBounds(nativeBounds);
            if (bounds.Width <= 0 || bounds.Height <= 0)
            {
                return;
            }

            GetWindowThreadProcessId(windowHandle, out var processId);
            windows.Add(new WindowInfo(
                windowHandle,
                (int)processId,
                GetProcessName((int)processId),
                title,
                bounds));
        }

        EnumWindows((windowHandle, _) =>
        {
            CollectWindow(windowHandle);
            return true;
        }, IntPtr.Zero);

        var inputDesktop = OpenInputDesktop(0, false, DesktopReadObjects | DesktopEnumerate);
        if (inputDesktop != IntPtr.Zero)
        {
            try
            {
                EnumDesktopWindows(inputDesktop, (windowHandle, _) =>
                {
                    CollectWindow(windowHandle);
                    return true;
                }, IntPtr.Zero);
            }
            finally
            {
                CloseDesktop(inputDesktop);
            }
        }

        return windows
            .OrderBy(window => window.Title, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public bool TryGetCaptureRegion(WindowSelection selection, out CaptureRegion? region)
    {
        var handle = new IntPtr(selection.WindowHandle);
        // A seleção pode ter sido descoberta no desktop interativo enquanto o
        // Bridge está executando em outro desktop auxiliar. Nessa situação,
        // IsWindowVisible/IsIconic pode retornar um estado incompleto apesar de
        // o HWND continuar válido. A existência do HWND, seu PID e um retângulo
        // válido são as verificações que permanecem confiáveis entre desktops.
        if (IsWindow(handle) && GetWindowRect(handle, out var nativeBounds))
        {
            GetWindowThreadProcessId(handle, out var processId);
            if (processId != selection.ProcessId)
            {
                region = null;
                return false;
            }

            var bounds = ToBounds(nativeBounds);
            if (bounds.Width <= 0 || bounds.Height <= 0)
            {
                region = null;
                return false;
            }

            region = new CaptureRegion(
                handle,
                selection.ProcessId,
                GetProcessName(selection.ProcessId),
                GetTitle(handle),
                bounds);
            return true;
        }

        // The selector can enumerate the user's input desktop while the
        // Bridge itself remains attached to an isolated desktop. In that
        // case user32 refuses to validate the HWND from this thread even
        // though the selected process and its saved bounds are still valid.
        if (!IsProcessAlive(selection.ProcessId) || selection.Bounds.Width <= 0 ||
            selection.Bounds.Height <= 0)
        {
            region = null;
            return false;
        }

        region = new CaptureRegion(
            handle,
            selection.ProcessId,
            selection.ProcessName,
            selection.Title,
            selection.Bounds);
        return true;
    }

    public static CaptureRegion GetVirtualScreenRegion()
    {
        var screen = System.Windows.Forms.Screen.PrimaryScreen
            ?? throw new InvalidOperationException("Nenhum monitor primário foi encontrado.");
        var bounds = screen.Bounds;
        return new CaptureRegion(
            MonitorFromPoint(new NativePoint(bounds.Left, bounds.Top), MonitorDefaultToNearest),
            0,
            "monitor",
            "Primary Monitor",
            new WindowBounds(bounds.Left, bounds.Top, bounds.Width, bounds.Height));
    }

    private const uint MonitorDefaultToNearest = 0x00000002;
    private const uint DesktopReadObjects = 0x0001;
    private const uint DesktopEnumerate = 0x0040;

    [DllImport("user32.dll")]
    private static extern IntPtr MonitorFromPoint(NativePoint point, uint flags);

    private static string GetTitle(IntPtr windowHandle)
    {
        var buffer = new StringBuilder(512);
        _ = GetWindowText(windowHandle, buffer, buffer.Capacity);
        return buffer.ToString();
    }

    private static string GetProcessName(int processId)
    {
        try
        {
            using var process = Process.GetProcessById(processId);
            return process.ProcessName;
        }
        catch (Exception) when (processId == 0 || processId == 4)
        {
            return "unknown";
        }
        catch (ArgumentException)
        {
            return "exited";
        }
    }

    private static bool IsProcessAlive(int processId)
    {
        try
        {
            using var process = Process.GetProcessById(processId);
            return !process.HasExited;
        }
        catch (ArgumentException)
        {
            return false;
        }
    }

    private static WindowBounds ToBounds(NativeRect rectangle)
    {
        return new WindowBounds(
            rectangle.Left,
            rectangle.Top,
            rectangle.Right - rectangle.Left,
            rectangle.Bottom - rectangle.Top);
    }

    [StructLayout(LayoutKind.Sequential)]
    private readonly record struct NativeRect(int Left, int Top, int Right, int Bottom);

    [StructLayout(LayoutKind.Sequential)]
    private readonly record struct NativePoint(int X, int Y);
}
