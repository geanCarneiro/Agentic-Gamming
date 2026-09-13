using System.Drawing;
using System.Windows.Forms;

namespace AgenticGaming.HostBridge;

public sealed class OverlayWindow : Form
{
    private const int WsExTransparent = 0x00000020;
    private const int WsExToolWindow = 0x00000080;
    private const int WsExLayered = 0x00080000;
    private const int WsExNoActivate = 0x08000000;

    private readonly bool _dryRun;
    private readonly Label _text;

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

    protected override bool ShowWithoutActivation => true;

    protected override CreateParams CreateParams
    {
        get
        {
            var parameters = base.CreateParams;
            parameters.ExStyle |= WsExTransparent | WsExToolWindow | WsExLayered | WsExNoActivate;
            return parameters;
        }
    }

    public void Update(CapturedFrame frame)
    {
        Bounds = new Rectangle(
            frame.Region.Bounds.Left,
            frame.Region.Bounds.Top,
            Math.Max(1, frame.Region.Bounds.Width),
            Math.Max(1, frame.Region.Bounds.Height));
        _text.Text = string.Join(Environment.NewLine,
            "AGENTIC GAMING | HOST BRIDGE",
            $"modo: {(_dryRun ? "DRY-RUN" : "LIVE")}",
            $"janela: {frame.Region.Title}",
            $"processo: {frame.Region.ProcessName} (PID {frame.Region.ProcessId})",
            $"frame: {frame.FrameId}",
            $"captura: {frame.Width}x{frame.Height}",
            $"timestamp: {frame.CapturedAtNs}");
        if (!Visible)
        {
            Show();
        }
    }
}
