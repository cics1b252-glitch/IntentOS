using System.Diagnostics;
using System.IO.Compression;
using System.Text.Json;
using Microsoft.Win32;

namespace IntentOS.Installer;

internal static class Program
{
    private const string Version = "0.4.4-alpha";
    private const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\IntentOS";

    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var uninstall = args.Any(a => a.Equals("/uninstall", StringComparison.OrdinalIgnoreCase));
        try
        {
            if (uninstall) Uninstall(); else Install();
        }
        catch (Exception ex)
        {
            WriteInstallLog($"failure type={ex.GetType().Name} message={ex.Message}");
            MessageBox.Show("A operação não foi concluída. Consulte o log de instalação em %TEMP%\\IntentOS-Install.log.",
                "Intent OS", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Environment.ExitCode = 1;
        }
    }

    private static string InstallRoot => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "IntentOS");
    private static string DataRoot => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "IntentOS", "Data");

    private static void Install()
    {
        if (MessageBox.Show("Instalar o Intent OS para este usuário?", "Intent OS Alpha",
                MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK) return;

        var payload = typeof(Program).Assembly.GetManifestResourceStream("IntentOS.Payload.zip")
            ?? throw new InvalidOperationException("O pacote interno de instalação está ausente.");
        var staging = InstallRoot + ".installing";
        if (Directory.Exists(staging)) Directory.Delete(staging, true);
        Directory.CreateDirectory(staging);
        using (payload) ZipFile.ExtractToDirectory(payload, staging, true);
        ValidatePayload(staging);

        if (Directory.Exists(InstallRoot)) Directory.Delete(InstallRoot, true);
        Directory.Move(staging, InstallRoot);
        Directory.CreateDirectory(DataRoot);
        foreach (var folder in new[] { "preferences", "logs", "cache", "future-kc", "backups", "updates" })
            Directory.CreateDirectory(Path.Combine(DataRoot, folder));

        var setupCopy = Path.Combine(InstallRoot, "app", "Uninstall-IntentOS.exe");
        File.Copy(Environment.ProcessPath!, setupCopy, true);
        CreateShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
            "Programs", "Intent OS.lnk"));
        if (MessageBox.Show("Criar também um atalho na Área de Trabalho?", "Intent OS",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            CreateShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "Intent OS.lnk"));
        RegisterUninstaller(setupCopy);
        WriteInstallLog($"installed version={Version} path={InstallRoot}");
        MessageBox.Show("Intent OS foi instalado com sucesso.", "Intent OS", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private static void Uninstall()
    {
        var deleteData = MessageBox.Show(
            "Deseja apagar também preferências e dados locais? Escolha Não para preservá-los.",
            "Desinstalar Intent OS", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question);
        if (deleteData == DialogResult.Cancel) return;

        DeleteShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", "Intent OS.lnk"));
        DeleteShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "Intent OS.lnk"));
        Registry.CurrentUser.DeleteSubKeyTree(UninstallKey, false);
        if (deleteData == DialogResult.Yes && Directory.Exists(DataRoot)) Directory.Delete(DataRoot, true);

        var root = InstallRoot;
        var cleanup = Path.Combine(Path.GetTempPath(), $"IntentOS-cleanup-{Guid.NewGuid():N}.cmd");
        File.WriteAllText(cleanup, $"@echo off\r\ntimeout /t 2 /nobreak >nul\r\nrmdir /s /q \"{root}\"\r\ndel /q \"%~f0\"\r\n",
            new System.Text.UTF8Encoding(false));
        Process.Start(new ProcessStartInfo("cmd.exe", $"/c \"{cleanup}\"") { CreateNoWindow = true, UseShellExecute = false });
        WriteInstallLog($"uninstalled preserveData={deleteData == DialogResult.No}");
        MessageBox.Show("Intent OS foi removido.", "Intent OS", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private static void ValidatePayload(string root)
    {
        foreach (var relative in new[] { @"app\IntentOS.exe", @"app\IntentOS.Bridge.exe", @"ui\shell\index.html", "version.json" })
            if (!File.Exists(Path.Combine(root, relative))) throw new InvalidDataException($"Arquivo obrigatório ausente: {relative}");
        using var metadata = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "version.json"), System.Text.Encoding.UTF8));
        var payloadVersion = metadata.RootElement.GetProperty("version").GetString();
        if (payloadVersion != Version)
            throw new InvalidDataException($"Pacote incompatível. Esperado {Version}; encontrado {payloadVersion ?? "desconhecido"}.");
    }

    private static void RegisterUninstaller(string uninstaller)
    {
        using var key = Registry.CurrentUser.CreateSubKey(UninstallKey);
        key.SetValue("DisplayName", "Intent OS Alpha");
        key.SetValue("DisplayVersion", Version);
        key.SetValue("Publisher", "Intent OS Project");
        key.SetValue("InstallLocation", InstallRoot);
        key.SetValue("UninstallString", $"\"{uninstaller}\" /uninstall");
        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
    }

    private static void CreateShortcut(string shortcut)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(shortcut)!);
        var target = Path.Combine(InstallRoot, "app", "IntentOS.exe");
        var shell = Type.GetTypeFromProgID("WScript.Shell") ?? throw new InvalidOperationException("Windows Script Host indisponível.");
        dynamic instance = Activator.CreateInstance(shell)!;
        dynamic link = instance.CreateShortcut(shortcut);
        link.TargetPath = target;
        link.WorkingDirectory = Path.GetDirectoryName(target);
        link.Description = "Intent OS";
        link.Save();
    }

    private static void DeleteShortcut(string path) { if (File.Exists(path)) File.Delete(path); }
    private static void WriteInstallLog(string message)
    {
        try { File.AppendAllText(Path.Combine(Path.GetTempPath(), "IntentOS-Install.log"),
            $"{DateTimeOffset.UtcNow:O} {message}{Environment.NewLine}",
            new System.Text.UTF8Encoding(false)); } catch { }
    }
}
