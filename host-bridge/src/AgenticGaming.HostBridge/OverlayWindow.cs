using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;

namespace AgenticGaming.HostBridge;

public sealed class OverlayWindow : Form
{
    private const int WsExTransparent = 0x00000020;
    private const int WsExToolWindow = 0x00000080;
    private const int WsExNoActivate = 0x08000000;

    private readonly bool _dryRun;
    private readonly Label _text;
    private BridgeVisionAnnotationsMessage? _annotations;
    private CapturedFrame? _currentFrame;
    private string? _currentFrameId;
    private int _currentFrameWidth;
    private int _currentFrameHeight;

    public OverlayWindow(bool dryRun)
    {
        _dryRun = dryRun;
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        ShowIcon = false;
        StartPosition = FormStartPosition.Manual;
        TopMost = true;
        BackColor = Color.Magenta;
        TransparencyKey = Color.Magenta;
        SetStyle(
            ControlStyles.UserPaint |
            ControlStyles.AllPaintingInWmPaint |
            ControlStyles.OptimizedDoubleBuffer |
            ControlStyles.SupportsTransparentBackColor,
            true);
        DoubleBuffered = true;
        Visible = false;

        _text = new Label
        {
            AutoSize = true,
            BackColor = Color.FromArgb(215, 0, 0, 0),
            ForeColor = Color.White,
            Font = new Font("Consolas", 10, FontStyle.Regular),
            Padding = new Padding(10),
            Margin = new Padding(10),
            Location = new Point(10, 10),
        };
        Controls.Add(_text);
    }

    public void UpdateAnnotations(BridgeVisionAnnotationsMessage annotations)
    {
        if (!string.Equals(annotations.FrameId, _currentFrameId, StringComparison.Ordinal) ||
            annotations.Width != _currentFrameWidth ||
            annotations.Height != _currentFrameHeight)
        {
            return;
        }

        _annotations = annotations;
        RefreshInfo();
        BringToFront();
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs eventArgs)
    {
        base.OnPaint(eventArgs);
        if (_annotations is null)
        {
            return;
        }

        eventArgs.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        foreach (var box in _annotations.Boxes)
        {
            if (box.Bbox is not { Length: 4 })
            {
                continue;
            }

            var x = (float)(box.Bbox[0] * ClientSize.Width);
            var y = (float)(box.Bbox[1] * ClientSize.Height);
            var width = (float)(box.Bbox[2] * ClientSize.Width);
            var height = (float)(box.Bbox[3] * ClientSize.Height);
            var color = TryParseOverlayColor(box.BboxColor, out var configuredColor)
                ? configuredColor
                : string.Equals(box.Kind, "character", StringComparison.OrdinalIgnoreCase)
                    ? Color.Red
                    : Color.Lime;
            using var outline = new Pen(Color.Black, 7);
            using var pen = new Pen(color, 3);
            eventArgs.Graphics.DrawRectangle(outline, x, y, width, height);
            eventArgs.Graphics.DrawRectangle(pen, x, y, width, height);

            var label = $"{box.Label} {box.State ?? "unknown"} {box.Confidence:P0}";
            using var labelFont = new Font("Consolas", 9, FontStyle.Bold);
            var labelSize = eventArgs.Graphics.MeasureString(label, labelFont);
            var labelY = Math.Max(0, y - labelSize.Height - 2);
            using var background = new SolidBrush(Color.FromArgb(190, 0, 0, 0));
            eventArgs.Graphics.FillRectangle(background, x, labelY, labelSize.Width + 6, labelSize.Height + 2);
            using var foreground = new SolidBrush(color);
            eventArgs.Graphics.DrawString(label, labelFont, foreground, x + 3, labelY + 1);
        }
    }

    protected override bool ShowWithoutActivation => true;

    protected override CreateParams CreateParams
    {
        get
        {
            var parameters = base.CreateParams;
            parameters.ExStyle |= WsExTransparent | WsExToolWindow | WsExNoActivate;
            return parameters;
        }
    }

    public void Update(CapturedFrame frame)
    {
        _currentFrame = frame;
        _currentFrameId = frame.FrameId;
        _currentFrameWidth = frame.Width;
        _currentFrameHeight = frame.Height;
        if (_annotations is not null &&
            (!string.Equals(_annotations.FrameId, _currentFrameId, StringComparison.Ordinal) ||
             _annotations.Width != _currentFrameWidth ||
             _annotations.Height != _currentFrameHeight))
        {
            _annotations = null;
        }

        Bounds = new Rectangle(
            frame.Region.Bounds.Left,
            frame.Region.Bounds.Top,
            Math.Max(1, frame.Region.Bounds.Width),
            Math.Max(1, frame.Region.Bounds.Height));
        RefreshInfo();
        Invalidate();
        if (!Visible)
        {
            Show();
        }
    }

    private static double GetCurrentAgeMs(BridgeVisionAnnotationsMessage annotations)
    {
        var nowNs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() * 1_000_000L;
        return Math.Max(0, nowNs - annotations.CapturedAtNs) / 1_000_000d;
    }

    private static bool TryParseOverlayColor(string? value, out Color color)
    {
        if (value is { Length: 7 } && value[0] == '#' && value.Skip(1).All(Uri.IsHexDigit))
        {
            color = Color.FromArgb(
                255,
                Convert.ToInt32(value.Substring(1, 2), 16),
                Convert.ToInt32(value.Substring(3, 2), 16),
                Convert.ToInt32(value.Substring(5, 2), 16));
            return true;
        }

        color = Color.Empty;
        return false;
    }

    private void RefreshInfo()
    {
        if (_currentFrame is not { } frame)
        {
            return;
        }

        var lines = new List<string>
        {
            "AGENTIC GAMING | HOST BRIDGE",
            $"modo: {(_dryRun ? "DRY-RUN" : "LIVE")}",
            $"janela: {frame.Region.Title}",
            $"processo: {frame.Region.ProcessName} (PID {frame.Region.ProcessId})",
            $"frame: {frame.FrameId}",
            $"captura: {frame.Width}x{frame.Height}",
            _annotations is null
                ? "visao: aguardando observacao deste frame"
                : $"visao: {_annotations.DetectorStatus}; cena={_annotations.Scene ?? "unknown"}; " +
                  $"processamento={_annotations.ProcessingMs ?? 0:F1} ms; " +
                  $"idade={GetCurrentAgeMs(_annotations):F0} ms",
        };
        if (_annotations is not null)
        {
            lines.AddRange(_annotations.Boxes.Take(4).Select(box =>
                $"{box.Label}: {box.State ?? "unknown"} ({box.Origin}); " +
                $"evidencia={string.Join(",", box.Evidence.Take(2))}"));
        }

        lines.Add($"timestamp: {frame.CapturedAtNs}");
        _text.Text = string.Join(Environment.NewLine, lines);
    }
}
