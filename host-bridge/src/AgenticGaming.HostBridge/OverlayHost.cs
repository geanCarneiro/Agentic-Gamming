using System.Windows.Forms;

namespace AgenticGaming.HostBridge;

public sealed class OverlayHost
{
    private readonly bool _dryRun;
    private readonly TaskCompletionSource<OverlayWindow> _ready = new(
        TaskCreationOptions.RunContinuationsAsynchronously);
    private Thread? _thread;

    public OverlayHost(bool dryRun)
    {
        _dryRun = dryRun;
    }

    public Task StartAsync(CancellationToken cancellationToken)
    {
        _thread = new Thread(() =>
        {
            try
            {
                Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
                Application.ThreadException += (_, eventArgs) =>
                {
                    Console.Error.WriteLine(eventArgs.Exception);
                    _ready.TrySetException(eventArgs.Exception);
                    Application.ExitThread();
                };
                var window = new OverlayWindow(_dryRun);
                _ = window.Handle;
                _ready.TrySetResult(window);
                Application.Run();
            }
            catch (Exception exception)
            {
                _ready.TrySetException(exception);
            }
        })
        {
            IsBackground = true,
            Name = "AgenticGaming.Overlay",
        };
        _thread.SetApartmentState(ApartmentState.STA);
        _thread.Start();
        return _ready.Task.WaitAsync(cancellationToken);
    }

    public async Task SetVisibleAsync(bool visible, CancellationToken cancellationToken)
    {
        var window = await _ready.Task.WaitAsync(cancellationToken);
        await InvokeAsync(window, () => window.Visible = visible, cancellationToken);
    }

    public async Task UpdateAsync(CapturedFrame frame, CancellationToken cancellationToken)
    {
        var window = await _ready.Task.WaitAsync(cancellationToken);
        await InvokeAsync(window, () => window.Update(frame), cancellationToken);
    }

    public async Task StopAsync()
    {
        if (!_ready.Task.IsCompletedSuccessfully)
        {
            return;
        }

        var window = await _ready.Task;
        try
        {
            await InvokeAsync(window, () =>
            {
                window.Close();
                Application.ExitThread();
            }, CancellationToken.None);
        }
        catch (InvalidOperationException)
        {
            // The UI thread already stopped; the bridge itself can still shut down normally.
        }
    }

    private static Task InvokeAsync(Control control, Action action, CancellationToken cancellationToken)
    {
        var completion = new TaskCompletionSource<object?>(TaskCreationOptions.RunContinuationsAsynchronously);
        try
        {
            if (control.IsDisposed || !control.IsHandleCreated)
            {
                completion.TrySetException(new InvalidOperationException("Overlay window handle is not available."));
            }
            else
            {
                control.BeginInvoke(new Action(() =>
                {
                    try
                    {
                        action();
                        completion.TrySetResult(null);
                    }
                    catch (Exception exception)
                    {
                        completion.TrySetException(exception);
                    }
                }));
            }
        }
        catch (Exception exception)
        {
            completion.TrySetException(exception);
        }
        return completion.Task.WaitAsync(cancellationToken);
    }
}
