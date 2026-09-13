using AgenticGaming.HostBridge;

var options = BridgeOptions.FromEnvironment(args);
var logger = new JsonLineLogger(options.LogPath);

using var cancellation = new CancellationTokenSource();
Console.CancelKeyPress += (_, eventArgs) =>
{
    eventArgs.Cancel = true;
    cancellation.Cancel();
};

OverlayHost? overlay = null;
try
{
    var windowCatalog = new WindowCatalog();
    WindowSelection? selection = null;
    Func<CaptureRegion?> regionProvider;

    if (options.UseDesktopCapture)
    {
        regionProvider = WindowCatalog.GetVirtualScreenRegion;
        await logger.WriteAsync("window.selection_bypassed", new { mode = "desktop" });
    }
    else
    {
        var profiles = GameProfileCatalog.Load(options.ProfilesDirectory);
        selection = await new WindowSelector(windowCatalog, logger)
            .SelectAsync(profiles, options.SelectionPath, cancellation.Token);
        if (selection is null)
        {
            await logger.WriteAsync("window.selection_cancelled", new { });
            Environment.ExitCode = 2;
            return;
        }

        var selectedWindow = selection;
        regionProvider = () => windowCatalog.TryGetCaptureRegion(selectedWindow, out var region) ? region : null;
    }

    var capture = new DesktopScreenCapture(
        options.PreviewPath,
        options.MaxCaptureWidth,
        options.MaxCaptureHeight,
        regionProvider,
        logger);
    overlay = new OverlayHost(options.DryRun);
    await overlay.StartAsync(cancellation.Token);
    var client = new CoreWebSocketClient(options, logger, overlay, selection?.ProfileId);

    await logger.WriteAsync("bridge.starting", new
    {
        endpoint = options.CoreWebSocketEndpoint,
        dry_run = options.DryRun,
        safe_capture = options.SafeCapture,
        capture_interval_ms = options.CaptureIntervalMs,
        max_capture_width = options.MaxCaptureWidth,
        max_capture_height = options.MaxCaptureHeight,
    });

    await client.RunAsync(capture, cancellation.Token);
}
catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
{
    await logger.WriteAsync("bridge.stopped", new { reason = "cancellation_requested" });
}
catch (Exception exception)
{
    await logger.WriteAsync("bridge.failed", new
    {
        exception = exception.GetType().FullName,
        message = exception.Message,
    });
    Console.Error.WriteLine(exception);
    Environment.ExitCode = 1;
}
finally
{
    if (overlay is not null)
    {
        try
        {
            await overlay.StopAsync();
        }
        catch (Exception exception)
        {
            await logger.WriteAsync("overlay.stop_failed", new
            {
                exception = exception.GetType().FullName,
                message = exception.Message,
            });
        }
    }
}
