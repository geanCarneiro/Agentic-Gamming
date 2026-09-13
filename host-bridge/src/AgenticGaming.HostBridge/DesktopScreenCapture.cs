using System;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;

namespace AgenticGaming.HostBridge;

public sealed class DesktopScreenCapture
{
    private const uint PwRenderFullContent = 0x00000002;

    private readonly string _previewPath;
    private readonly int _maxWidth;
    private readonly int _maxHeight;
    private readonly Func<CaptureRegion?> _regionProvider;
    private readonly JsonLineLogger _logger;

    public DesktopScreenCapture(
        string previewPath,
        int maxWidth,
        int maxHeight,
        Func<CaptureRegion?> regionProvider,
        JsonLineLogger logger)
    {
        _previewPath = Path.GetFullPath(previewPath);
        _maxWidth = maxWidth;
        _maxHeight = maxHeight;
        _regionProvider = regionProvider;
        _logger = logger;
        Directory.CreateDirectory(Path.GetDirectoryName(_previewPath)!);
    }

    public async Task<CapturedFrame> CaptureAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        var region = _regionProvider();
        if (region is null)
        {
            throw new InvalidOperationException("The selected game window is no longer valid.");
        }

        var bounds = new Rectangle(
            region.Bounds.Left,
            region.Bounds.Top,
            region.Bounds.Width,
            region.Bounds.Height);
        using var source = region.WindowHandle == IntPtr.Zero
            ? CaptureDesktop(bounds)
            : CaptureWindow(region.WindowHandle, bounds);

        var scale = Math.Min(1d, Math.Min((double)_maxWidth / source.Width, (double)_maxHeight / source.Height));
        var outputWidth = Math.Max(1, (int)Math.Round(source.Width * scale));
        var outputHeight = Math.Max(1, (int)Math.Round(source.Height * scale));
        using var bitmap = new Bitmap(outputWidth, outputHeight, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(bitmap))
        {
            graphics.DrawImage(
                source,
                new Rectangle(0, 0, outputWidth, outputHeight),
                0,
                0,
                source.Width,
                source.Height,
                GraphicsUnit.Pixel);
        }

        await using var stream = new MemoryStream();
        bitmap.Save(stream, ImageFormat.Png);
        var bytes = stream.ToArray();
        var frame = new CapturedFrame(
            Guid.NewGuid().ToString("N"),
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() * 1_000_000,
            bitmap.Width,
            bitmap.Height,
            bytes,
            region);

        await File.WriteAllBytesAsync(_previewPath, bytes, cancellationToken);
        await _logger.WriteAsync("capture.frame", new
        {
            frame_id = frame.FrameId,
            width = frame.Width,
            height = frame.Height,
            bytes = frame.PngBytes.Length,
            window_title = region.Title,
            process_id = region.ProcessId,
            preview_path = _previewPath,
        }, cancellationToken);

        return frame;
    }

    private static Bitmap CaptureDesktop(Rectangle bounds)
    {
        var bitmap = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format32bppArgb);
        try
        {
            using var graphics = Graphics.FromImage(bitmap);
            graphics.CopyFromScreen(
                bounds.Left,
                bounds.Top,
                0,
                0,
                bounds.Size,
                CopyPixelOperation.SourceCopy);
            return bitmap;
        }
        catch
        {
            bitmap.Dispose();
            throw;
        }
    }

    private static Bitmap CaptureWindow(IntPtr windowHandle, Rectangle bounds)
    {
        var bitmap = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format32bppArgb);
        using var graphics = Graphics.FromImage(bitmap);
        var deviceContext = graphics.GetHdc();
        try
        {
            if (!PrintWindow(windowHandle, deviceContext, PwRenderFullContent))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Could not capture the selected window.");
            }
            return bitmap;
        }
        finally
        {
            graphics.ReleaseHdc(deviceContext);
        }
    }

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool PrintWindow(IntPtr windowHandle, IntPtr deviceContext, uint flags);
}
