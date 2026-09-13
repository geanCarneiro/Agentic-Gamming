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
        EnumWindows((windowHandle, _) =>
        {
            if (!IsWindowVisible(windowHandle) || IsIconic(windowHandle))
            {
                return true;
            }

            var title = GetTitle(windowHandle);
            if (string.IsNullOrWhiteSpace(title) || !GetWindowRect(windowHandle, out var nativeBounds))
            {
                return true;
            }

            var bounds = ToBounds(nativeBounds);
            if (bounds.Width <= 0 || bounds.Height <= 0)
            {
                return true;
            }

            GetWindowThreadProcessId(windowHandle, out var processId);
            windows.Add(new WindowInfo(
                windowHandle,
                (int)processId,
                GetProcessName((int)processId),
                title,
                bounds));
            return true;
        }, IntPtr.Zero);

        return windows
            .OrderBy(window => window.Title, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public bool TryGetCaptureRegion(WindowSelection selection, out CaptureRegion? region)
    {
        var handle = new IntPtr(selection.WindowHandle);
        if (!IsWindow(handle) || !IsWindowVisible(handle) || IsIconic(handle) ||
            !GetWindowRect(handle, out var nativeBounds))
        {
            region = null;
            return false;
        }

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

    public static CaptureRegion GetVirtualScreenRegion()
    {
        var bounds = System.Windows.Forms.SystemInformation.VirtualScreen;
        return new CaptureRegion(
            IntPtr.Zero,
            0,
            "desktop",
            "Virtual Screen",
            new WindowBounds(bounds.Left, bounds.Top, bounds.Width, bounds.Height));
    }

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
}
