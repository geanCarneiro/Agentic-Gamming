using System.Runtime.InteropServices;
using Windows.Graphics;
using Windows.Graphics.Capture;
using Windows.Graphics.DirectX;
using Windows.Graphics.DirectX.Direct3D11;
using Lvhang.WindowsCapture;
using WinRT;

namespace AgenticGaming.HostBridge;

/// <summary>
/// Captura uma janela ou monitor por meio do compositor do Windows.
/// Diferentemente de GDI/PrintWindow, esse caminho consegue ler superfícies
/// renderizadas por DirectDraw/Direct3D sem depender de a janela estar visível
/// no DC da área de trabalho.
/// </summary>
internal sealed class WindowsGraphicsCapture : IDisposable
{
    private static readonly Guid GraphicsCaptureItemGuid =
        new("79C3F95B-31F7-4EC2-A464-632EF5D30760");

    private readonly object _gate = new();
    private IDirect3DDevice? _device;
    private Direct3D11CaptureFramePool? _framePool;
    private GraphicsCaptureSession? _session;
    private GraphicsCaptureItem? _item;
    private CapturedBitmap? _latest;
    private IntPtr _target;
    private bool _monitor;
    private bool _started;
    private Exception? _lastError;

    public static bool IsSupported()
    {
        try
        {
            return GraphicsCaptureSession.IsSupported();
        }
        catch
        {
            return false;
        }
    }

    public async Task<Bitmap> CaptureWindowAsync(
        IntPtr windowHandle,
        int expectedWidth,
        int expectedHeight,
        CancellationToken cancellationToken)
    {
        await EnsureStartedAsync(windowHandle, monitor: false, expectedWidth, expectedHeight, cancellationToken);
        return await WaitForBitmapAsync(cancellationToken);
    }

    public async Task<Bitmap> CaptureMonitorAsync(
        IntPtr monitorHandle,
        int expectedWidth,
        int expectedHeight,
        CancellationToken cancellationToken)
    {
        await EnsureStartedAsync(monitorHandle, monitor: true, expectedWidth, expectedHeight, cancellationToken);
        return await WaitForBitmapAsync(cancellationToken);
    }

    private async Task EnsureStartedAsync(
        IntPtr target,
        bool monitor,
        int expectedWidth,
        int expectedHeight,
        CancellationToken cancellationToken)
    {
        lock (_gate)
        {
            if (_started && _target == target && _monitor == monitor)
            {
                return;
            }
        }

        StopCapture();
        cancellationToken.ThrowIfCancellationRequested();

        if (!IsSupported())
        {
            throw new PlatformNotSupportedException(
                "Windows Graphics Capture não está disponível nesta versão/sessão do Windows.");
        }

        _device = Direct3D11Helper.CreateDevice();
        _item = CreateCaptureItem(target, monitor);
        var size = _item.Size;
        if (size.Width <= 0 || size.Height <= 0)
        {
            size = new SizeInt32
            {
                Width = expectedWidth,
                Height = expectedHeight,
            };
        }

        if (size.Width <= 0 || size.Height <= 0)
        {
            throw new InvalidOperationException("O alvo de captura não possui dimensões válidas.");
        }

        _framePool = Direct3D11CaptureFramePool.CreateFreeThreaded(
            _device,
            DirectXPixelFormat.B8G8R8A8UIntNormalized,
            2,
            size);
        _framePool.FrameArrived += OnFrameArrived;
        _session = _framePool.CreateCaptureSession(_item);
        _session.StartCapture();

        lock (_gate)
        {
            _target = target;
            _monitor = monitor;
            _started = true;
            _lastError = null;
        }

        // O primeiro frame chega de forma assíncrona. Este pequeno yield evita
        // que o primeiro polling coincida com a inicialização do compositor.
        await Task.Yield();
    }

    private async Task<Bitmap> WaitForBitmapAsync(CancellationToken cancellationToken)
    {
        while (true)
        {
            CapturedBitmap? latest;
            Exception? error;
            lock (_gate)
            {
                latest = _latest;
                _latest = null;
                error = _lastError;
            }

            if (latest is not null)
            {
                using var stream = new MemoryStream(latest.PngBytes, writable: false);
                return new Bitmap(stream);
            }

            if (error is not null)
            {
                throw new InvalidOperationException(
                    "Windows Graphics Capture não produziu um frame.", error);
            }

            await Task.Delay(10, cancellationToken);
        }
    }

    private void OnFrameArrived(Direct3D11CaptureFramePool sender, object args)
    {
        try
        {
            using var frame = sender.TryGetNextFrame();
            if (frame is null)
            {
                return;
            }

            using var bitmap = frame.ToBitmap();
            using var stream = new MemoryStream();
            bitmap.Save(stream, System.Drawing.Imaging.ImageFormat.Png);

            lock (_gate)
            {
                _latest = new CapturedBitmap(
                    frame.ContentSize.Width,
                    frame.ContentSize.Height,
                    stream.ToArray());
                _lastError = null;
            }
        }
        catch (Exception exception)
        {
            lock (_gate)
            {
                _lastError = exception;
            }
        }
    }

    private static GraphicsCaptureItem CreateCaptureItem(IntPtr target, bool monitor)
    {
        var className = "Windows.Graphics.Capture.GraphicsCaptureItem";
        var createStringResult = WindowsCreateString(
            className,
            (uint)className.Length,
            out var classNameHandle);
        Marshal.ThrowExceptionForHR(createStringResult);

        IntPtr factoryPointer;
        try
        {
            var interopGuid = typeof(IGraphicsCaptureItemInterop).GUID;
            Marshal.ThrowExceptionForHR(
                RoGetActivationFactory(classNameHandle, ref interopGuid, out factoryPointer));
        }
        finally
        {
            WindowsDeleteString(classNameHandle);
        }

        var interop = (IGraphicsCaptureItemInterop)Marshal.GetObjectForIUnknown(factoryPointer);
        Marshal.Release(factoryPointer);
        var itemGuid = GraphicsCaptureItemGuid;
        var itemPointer = monitor
            ? interop.CreateForMonitor(target, ref itemGuid)
            : interop.CreateForWindow(target, ref itemGuid);

        if (itemPointer == IntPtr.Zero)
        {
            throw new InvalidOperationException("O Windows não retornou um item de captura.");
        }

        try
        {
            return MarshalInterface<GraphicsCaptureItem>.FromAbi(itemPointer);
        }
        finally
        {
            Marshal.Release(itemPointer);
        }
    }

    public void Dispose() => StopCapture();

    private void StopCapture()
    {
        lock (_gate)
        {
            _started = false;
            _latest = null;
            _lastError = null;
        }

        if (_framePool is not null)
        {
            _framePool.FrameArrived -= OnFrameArrived;
            _framePool.Dispose();
            _framePool = null;
        }

        _session?.Dispose();
        _session = null;
        _item = null;
        _device?.Dispose();
        _device = null;
    }

    private sealed record CapturedBitmap(int Width, int Height, byte[] PngBytes);

    [ComImport]
    [Guid("3628E81B-3CAC-4C60-B7F4-23CE0E0C3356")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IGraphicsCaptureItemInterop
    {
        IntPtr CreateForWindow(IntPtr window, ref Guid iid);

        IntPtr CreateForMonitor(IntPtr monitor, ref Guid iid);
    }

    [DllImport("combase.dll")]
    private static extern int WindowsCreateString(
        [MarshalAs(UnmanagedType.LPWStr)] string sourceString,
        uint length,
        out IntPtr hstring);

    [DllImport("combase.dll")]
    private static extern int WindowsDeleteString(IntPtr hstring);

    [DllImport("combase.dll")]
    private static extern int RoGetActivationFactory(
        IntPtr activatableClassId,
        ref Guid iid,
        out IntPtr factory);
}
