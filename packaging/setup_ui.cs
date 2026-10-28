using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace OspreySetup
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool silent = Environment.GetEnvironmentVariable("OSPREY_SILENT") == "1";
            string destOverride = null;
            foreach (string arg in args)
            {
                string value = arg.Trim();
                if (value == "/S" || value == "--silent" || value == "-s")
                {
                    silent = true;
                }
                else if (value.StartsWith("/D=", StringComparison.OrdinalIgnoreCase))
                {
                    destOverride = value.Substring(3).Trim('"');
                }
            }

            if (silent)
            {
                Environment.Exit(Installer.RunSilent(destOverride));
            }
            Application.Run(new InstallerForm());
        }
    }

    internal static class Payload
    {
        public static byte[] Read(string self)
        {
            using (FileStream stream = File.OpenRead(self))
            {
                if (stream.Length < 16)
                {
                    throw new Exception("安装包不完整。");
                }
                stream.Seek(-8, SeekOrigin.End);
                byte[] lengthBytes = new byte[8];
                stream.Read(lengthBytes, 0, 8);
                long length = BitConverter.ToInt64(lengthBytes, 0);
                long offset = stream.Length - 8 - length;
                if (offset < 0 || length <= 0 || length > 512L * 1024 * 1024)
                {
                    throw new Exception("安装包数据无效。");
                }
                stream.Seek(offset, SeekOrigin.Begin);
                byte[] data = new byte[length];
                int read = 0;
                while (read < length)
                {
                    int chunk = stream.Read(data, read, (int)(length - read));
                    if (chunk <= 0)
                    {
                        throw new Exception("安装包数据被截断。");
                    }
                    read += chunk;
                }
                return data;
            }
        }

        public static void Extract(byte[] payload, string dest)
        {
            Directory.CreateDirectory(dest);
            using (MemoryStream memory = new MemoryStream(payload))
            using (ZipArchive archive = new ZipArchive(memory, ZipArchiveMode.Read))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string name = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                    if (name.Contains(".."))
                    {
                        continue;
                    }
                    string target = Path.Combine(dest, name);
                    if (name.EndsWith(Path.DirectorySeparatorChar.ToString()))
                    {
                        Directory.CreateDirectory(target);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    entry.ExtractToFile(target, true);
                }
            }
        }
    }

    internal static class Installer
    {
        public static void Log(string message)
        {
            try
            {
                File.AppendAllText(
                    Path.Combine(Path.GetTempPath(), "osprey-setup.log"),
                    DateTime.Now.ToString("s") + "  " + message + Environment.NewLine);
            }
            catch
            {
            }
        }

        public static string DefaultDirectory()
        {
            string forced = Environment.GetEnvironmentVariable("OSPREY_TEST_DEST");
            if (!string.IsNullOrEmpty(forced))
            {
                return forced;
            }
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                "Programs", "Osprey");
        }

        public static void CreateShortcuts(string dest)
        {
            string script = Path.Combine(dest, "shortcuts.ps1");
            if (!File.Exists(script))
            {
                return;
            }
            ProcessStartInfo info = new ProcessStartInfo(
                "powershell",
                "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\" -Dest \"" + dest + "\"");
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            using (Process process = Process.Start(info))
            {
                process.WaitForExit();
            }
        }

        public static void InstallTo(string dest)
        {
            Log("reading payload from " + Process.GetCurrentProcess().MainModule.FileName);
            byte[] payload = Payload.Read(Process.GetCurrentProcess().MainModule.FileName);
            Log("payload bytes: " + payload.Length.ToString());
            Payload.Extract(payload, dest);
            Log("extracted to " + dest);
            if (Environment.GetEnvironmentVariable("OSPREY_NO_SHORTCUTS") != "1")
            {
                try
                {
                    CreateShortcuts(dest);
                }
                catch
                {
                    // Shortcuts are a convenience; never fail the install for them.
                }
            }
        }

        public static int RunSilent(string destOverride)
        {
            try
            {
                string dest = string.IsNullOrEmpty(destOverride) ? DefaultDirectory() : destOverride;
                Log("silent install to " + dest);
                InstallTo(dest);
                if (Environment.GetEnvironmentVariable("OSPREY_NO_LAUNCH") != "1")
                {
                    Start(dest);
                }
                Log("silent install finished");
                return 0;
            }
            catch (Exception error)
            {
                Log("silent install failed: " + error);
                return 1;
            }
        }

        public static void Start(string dest)
        {
            ProcessStartInfo info = new ProcessStartInfo(Path.Combine(dest, "osprey.bat"));
            info.UseShellExecute = true;
            info.WorkingDirectory = dest;
            Process.Start(info);
        }
    }

    public class InstallerForm : Form
    {
        private const string TermsText =
            "1. 本软件仅用于您拥有或已获得明确授权的系统上的界面自动化（截屏、模板匹配、模拟键鼠）。\r\n\r\n" +
            "2. 本软件不用于任何形式的挂课、刷课、刷学习时长、代考或其他学术作弊，也不针对任何教学平台提供功能。\r\n\r\n" +
            "3. 严禁将本软件用于违反法律法规、平台服务条款或学校规定的用途。因使用本软件产生的一切后果（包括但不限于账号封禁、纪律处分、法律责任）由使用者自行承担，作者不承担任何责任。\r\n\r\n" +
            "4. 软件按“现状”提供，不附带任何担保。请先在无关紧要的窗口试运行，确认无误后再实际使用。\r\n\r\n" +
            "5. 本软件不上传任何数据，配置和模板都保存在本机。";

        private readonly TextBox pathBox;
        private readonly Button browseButton;
        private readonly CheckBox agreeBox;
        private readonly Button installButton;
        private readonly ProgressBar progress;
        private readonly Label statusLabel;
        private readonly CheckBox launchBox;
        private readonly Label termsTitle;
        private readonly RichTextBox termsBox;
        private string installedDir;
        private bool installed;

        public InstallerForm()
        {
            Text = "Osprey 0.1.0 安装程序";
            ClientSize = new Size(620, 660);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 9F);
            BackColor = Color.FromArgb(246, 248, 252);

            Label title = new Label();
            title.Text = "Osprey 屏幕视觉自动化";
            title.Font = new Font("Microsoft YaHei UI", 16F, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(20, 30, 48);
            title.SetBounds(20, 16, 560, 32);
            Controls.Add(title);

            Label subtitle = new Label();
            subtitle.Text = "版本 0.1.0  ·  Windows 10 / 11 x64  ·  安装后无需 Python";
            subtitle.ForeColor = Color.FromArgb(90, 100, 120);
            subtitle.SetBounds(22, 52, 560, 20);
            Controls.Add(subtitle);

            termsTitle = new Label();
            termsTitle.Text = "使用须知（请务必阅读）";
            termsTitle.Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold);
            termsTitle.SetBounds(20, 84, 300, 22);
            Controls.Add(termsTitle);

            termsBox = new RichTextBox();
            termsBox.ReadOnly = true;
            termsBox.BorderStyle = BorderStyle.FixedSingle;
            termsBox.BackColor = Color.White;
            termsBox.SetBounds(20, 110, 580, 286);
            termsBox.Text = TermsText;
            termsBox.Select(0, 0);
            Controls.Add(termsBox);

            agreeBox = new CheckBox();
            agreeBox.Text = "我已阅读并同意上述使用须知，并自行承担使用本软件的一切后果";
            agreeBox.SetBounds(20, 406, 580, 24);
            agreeBox.CheckedChanged += delegate { installButton.Enabled = agreeBox.Checked; };
            Controls.Add(agreeBox);

            Label pathLabel = new Label();
            pathLabel.Text = "安装位置";
            pathLabel.SetBounds(20, 444, 120, 20);
            Controls.Add(pathLabel);

            pathBox = new TextBox();
            pathBox.Text = Installer.DefaultDirectory();
            pathBox.SetBounds(20, 466, 470, 24);
            Controls.Add(pathBox);

            browseButton = new Button();
            browseButton.Text = "浏览…";
            browseButton.SetBounds(500, 465, 100, 26);
            browseButton.Click += BrowseClick;
            Controls.Add(browseButton);

            progress = new ProgressBar();
            progress.Style = ProgressBarStyle.Marquee;
            progress.SetBounds(20, 506, 580, 14);
            progress.Visible = false;
            Controls.Add(progress);

            statusLabel = new Label();
            statusLabel.Text = "勾选上方同意项后才能继续安装。";
            statusLabel.ForeColor = Color.FromArgb(90, 100, 120);
            statusLabel.SetBounds(20, 526, 580, 22);
            Controls.Add(statusLabel);

            launchBox = new CheckBox();
            launchBox.Text = "安装完成后启动 Osprey";
            launchBox.Checked = true;
            launchBox.SetBounds(20, 556, 300, 24);
            launchBox.Visible = false;
            Controls.Add(launchBox);

            installButton = new Button();
            installButton.Text = "同意并安装";
            installButton.Enabled = false;
            installButton.SetBounds(360, 596, 128, 34);
            installButton.Click += InstallClick;
            Controls.Add(installButton);

            Button cancelButton = new Button();
            cancelButton.Text = "取消";
            cancelButton.SetBounds(500, 596, 100, 34);
            cancelButton.Click += delegate { Close(); };
            Controls.Add(cancelButton);
        }

        private void BrowseClick(object sender, EventArgs e)
        {
            using (FolderBrowserDialog dialog = new FolderBrowserDialog())
            {
                dialog.Description = "选择 Osprey 的安装位置";
                dialog.SelectedPath = pathBox.Text;
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    pathBox.Text = dialog.SelectedPath;
                }
            }
        }

        private async void InstallClick(object sender, EventArgs e)
        {
            if (installed)
            {
                Close();
                return;
            }

            string dest = pathBox.Text.Trim();
            if (dest.Length == 0)
            {
                MessageBox.Show(this, "请填写安装位置。", "Osprey", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            try
            {
                Directory.CreateDirectory(dest);
            }
            catch (Exception error)
            {
                MessageBox.Show(this, "无法创建安装目录：\r\n" + error.Message, "Osprey",
                                MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            installButton.Enabled = false;
            browseButton.Enabled = false;
            pathBox.Enabled = false;
            agreeBox.Enabled = false;
            progress.Visible = true;
            statusLabel.Text = "正在安装，请稍候…";

            string failure = null;
            await Task.Run(delegate
            {
                try
                {
                    Installer.InstallTo(dest);
                }
                catch (Exception error)
                {
                    failure = error.Message;
                }
            });

            progress.Visible = false;
            if (failure != null)
            {
                statusLabel.Text = "安装失败。";
                MessageBox.Show(this, "安装失败：\r\n" + failure, "Osprey",
                                MessageBoxButtons.OK, MessageBoxIcon.Error);
                installButton.Enabled = true;
                browseButton.Enabled = true;
                pathBox.Enabled = true;
                agreeBox.Enabled = true;
                return;
            }

            installed = true;
            installedDir = dest;
            launchBox.Visible = true;
            installButton.Text = "完成";
            installButton.Enabled = true;
            statusLabel.Text = "安装完成，位置：" + dest;
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            base.OnFormClosed(e);
            if (installed && launchBox.Checked && installedDir != null)
            {
                try
                {
                    Installer.Start(installedDir);
                }
                catch
                {
                }
            }
        }
    }
}
