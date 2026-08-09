using System.Diagnostics;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace IntentOS.WindowsHost;

internal static class Program
{
    internal const string Version = "0.4.4-alpha";

    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        using var mutex = new Mutex(true, "Local\\IntentOS.WindowsHost", out var firstInstance);
        if (!firstInstance)
        {
            MessageBox.Show("O Intent OS já está aberto.", "Intent OS", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        try
        {
            var paths = AppPaths.Resolve();
            paths.Initialize();
            AppLog.Initialize(paths.Logs);
            AppLog.Event("host_started", $"version={Version} install={paths.InstallRoot} data={paths.DataRoot}");
            Application.Run(new MainWindow(paths));
        }
        catch (Exception ex)
        {
            AppLog.Write($"fatal type={ex.GetType().Name} message={ex.Message}");
            MessageBox.Show(
                "O Intent OS não pôde iniciar. Consulte o diagnóstico em %LOCALAPPDATA%\\IntentOS\\Data\\logs.",
                "Intent OS — erro de inicialização", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}

internal sealed record AppPaths(string InstallRoot, string DataRoot)
{
    internal string UiRoot => Path.Combine(InstallRoot, "ui");
    internal string ShellEntry => Path.Combine(UiRoot, "shell", "index.html");
    internal string Preferences => Path.Combine(DataRoot, "preferences");
    internal string Logs => Path.Combine(DataRoot, "logs");
    internal string WebViewData => Path.Combine(DataRoot, "cache", "webview2");

    internal static AppPaths Resolve()
    {
        var executable = Environment.ProcessPath ?? Application.ExecutablePath;
        var appDirectory = Path.GetDirectoryName(executable) ?? AppContext.BaseDirectory;
        var installRoot = Path.GetFullPath(Path.Combine(appDirectory, ".."));
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return new(installRoot, Path.Combine(local, "IntentOS", "Data"));
    }

    internal void Initialize()
    {
        foreach (var path in new[] { Preferences, Logs, WebViewData, Path.Combine(DataRoot, "cache"),
                     Path.Combine(DataRoot, "future-kc"), Path.Combine(DataRoot, "backups"),
                     Path.Combine(DataRoot, "updates") })
            Directory.CreateDirectory(path);

        var preferenceFile = Path.Combine(Preferences, "host.json");
        if (!File.Exists(preferenceFile))
            File.WriteAllText(preferenceFile, JsonSerializer.Serialize(new
            {
                firstRunUtc = DateTimeOffset.UtcNow,
                version = Program.Version,
                channel = "alpha",
                localDemo = true
            }, new JsonSerializerOptions { WriteIndented = true }), new System.Text.UTF8Encoding(false));

        if (!File.Exists(ShellEntry))
            throw new FileNotFoundException("Os arquivos da interface local não foram encontrados.", ShellEntry);
    }
}

internal static class AppLog
{
    private static string? _hostFile;
    private static string? _bridgeFile;
    internal static void Initialize(string directory)
    {
        _hostFile = Path.Combine(directory, "host.log");
        _bridgeFile = Path.Combine(directory, "bridge.log");
    }
    internal static void Event(string name, string detail = "") => Write($"event={name} {detail}".TrimEnd());
    internal static void Write(string message) => Append(_hostFile, message);
    internal static void WriteBridge(string message) => Append(_bridgeFile, message);
    private static void Append(string? file, string message)
    {
        if (file is null) return;
        try { File.AppendAllText(file, $"{DateTimeOffset.UtcNow:O} {message}{Environment.NewLine}",
            new System.Text.UTF8Encoding(false)); }
        catch { /* Logging must never prevent startup or shutdown. */ }
    }
}

internal enum StartupState
{
    Launching, LoadingHost, LoadingWebView, LoadingShell, StartingBridge,
    Handshaking, Ready, Degraded, Failed, ShuttingDown
}

internal sealed class MainWindow : Form
{
    private static readonly TimeSpan WebViewEnvironmentTimeout = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan WebViewInitializationTimeout = TimeSpan.FromSeconds(20);
    private static readonly TimeSpan ShellNavigationTimeout = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan TotalStartupTimeout = TimeSpan.FromSeconds(45);

    private readonly AppPaths _paths;
    private WebView2 _view = new() { Dock = DockStyle.Fill, Visible = false };
    private readonly Panel _startup = new() { Dock = DockStyle.Fill, BackColor = Color.FromArgb(247, 247, 250) };
    private readonly Label _title = new() { AutoSize = true, Font = new Font("Segoe UI", 24, FontStyle.Bold), Text = "Intent OS" };
    private readonly Label _status = new() { AutoSize = true, Font = new Font("Segoe UI", 11), Text = "Preparando…" };
    private readonly FlowLayoutPanel _actions = new() { AutoSize = true, FlowDirection = FlowDirection.LeftToRight, Visible = false };
    private CancellationTokenSource _startupCancellation = new();
    private ProductController? _product;
    private bool _safeMode;
    private bool _closing;
    private StartupState _startupState = StartupState.Launching;

    internal MainWindow(AppPaths paths)
    {
        _paths = paths;
        Text = "Intent OS";
        Width = 1280;
        Height = 820;
        MinimumSize = new Size(760, 560);
        StartPosition = FormStartPosition.CenterScreen;
        BuildStartupSurface();
        Controls.Add(_view);
        Controls.Add(_startup);
        Shown += OnShown;
        FormClosing += OnFormClosing;
        FormClosed += OnFormClosed;
    }

    private void BuildStartupSurface()
    {
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5, Padding = new Padding(48) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 40));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 60));
        _title.Anchor = AnchorStyles.None;
        _status.Anchor = AnchorStyles.None;
        _actions.Anchor = AnchorStyles.None;
        layout.Controls.Add(new Panel(), 0, 0);
        layout.Controls.Add(_title, 0, 1);
        layout.Controls.Add(_status, 0, 2);
        layout.Controls.Add(_actions, 0, 3);
        _startup.Controls.Add(layout);
    }

    private async void OnShown(object? sender, EventArgs args) => await StartAsync(false);

    private async Task StartAsync(bool safeMode)
    {
        if (_closing) return;
        _safeMode = safeMode;
        _startupCancellation.Cancel();
        _startupCancellation.Dispose();
        _startupCancellation = new CancellationTokenSource(TotalStartupTimeout);
        var token = _startupCancellation.Token;
        ShowLoading(safeMode ? "Iniciando em modo seguro…" : "Preparando seu espaço…");

        try
        {
            SetStartupState(StartupState.LoadingHost);
            await Task.Yield(); // Allow the native surface and window controls to paint first.

            SetStartupState(StartupState.LoadingWebView);
            AppLog.Event("webview_environment_started");
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: _paths.WebViewData)
                .WaitAsync(WebViewEnvironmentTimeout, token);
            await _view.EnsureCoreWebView2Async(environment).WaitAsync(WebViewInitializationTimeout, token);
            ConfigureWebView();
            _product = new ProductController(_paths, _view.CoreWebView2, safeMode);
            _view.CoreWebView2.WebMessageReceived += _product.HandleMessageAsync;
            AppLog.Event("webview_ready");

            SetStartupState(StartupState.LoadingShell);
            AppLog.Event("shell_navigation_started");
            await NavigateShellAsync(token).WaitAsync(ShellNavigationTimeout, token);
            AppLog.Event("shell_loaded");
            _view.Visible = true;
            _startup.Visible = false;

            SetStartupState(StartupState.StartingBridge);
            SetStartupState(StartupState.Handshaking);
            var bridgeReady = await _product.InitializeAsync(token);
            if (bridgeReady)
            {
                AppLog.Event("bridge_ready");
                AppLog.Event("kernel_ready");
                AppLog.Event("session_restored", safeMode ? "safeMode=true" : "safeMode=false");
                SetStartupState(StartupState.Ready);
                AppLog.Event("app_ready");
            }
            else
            {
                SetStartupState(StartupState.Degraded);
                _product.NotifyStartupState("degraded");
            }
        }
        catch (OperationCanceledException) when (_closing) { }
        catch (Exception ex)
        {
            SetStartupState(StartupState.Failed);
            AppLog.Write($"startup-failure state={_startupState} type={ex.GetType().Name} message={ex.Message}");
            ShowFailure(ex);
        }
    }

    private void ConfigureWebView()
    {
        _view.CoreWebView2.Settings.AreDevToolsEnabled = false;
        _view.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
        _view.CoreWebView2.Settings.IsStatusBarEnabled = false;
        _view.CoreWebView2.SetVirtualHostNameToFolderMapping(
            "intent.local", _paths.UiRoot, CoreWebView2HostResourceAccessKind.DenyCors);
        _view.CoreWebView2.ProcessFailed += (_, e) =>
        {
            AppLog.Write($"webview-failure kind={e.ProcessFailedKind}");
            if (!_closing) BeginInvoke(() => ShowFailure(new InvalidOperationException("A interface foi interrompida.")));
        };
    }

    private Task NavigateShellAsync(CancellationToken token)
    {
        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        void Completed(object? sender, CoreWebView2NavigationCompletedEventArgs e)
        {
            _view.CoreWebView2.NavigationCompleted -= Completed;
            if (e.IsSuccess) completion.TrySetResult();
            else completion.TrySetException(new InvalidOperationException($"Falha ao abrir a interface: {e.WebErrorStatus}."));
        }
        _view.CoreWebView2.NavigationCompleted += Completed;
        token.Register(() => completion.TrySetCanceled(token));
        _view.Source = new Uri($"https://intent.local/shell/index.html?host=product-alpha&safeMode={_safeMode.ToString().ToLowerInvariant()}");
        return completion.Task;
    }

    private void SetStartupState(StartupState state)
    {
        _startupState = state;
        var wire = ToWireState(state);
        AppLog.Event(wire);
        _status.Text = state switch
        {
            StartupState.LoadingWebView => "Preparando a janela…",
            StartupState.LoadingShell => "Carregando sua experiência…",
            StartupState.StartingBridge => "Iniciando o núcleo…",
            StartupState.Handshaking => "Verificando o núcleo…",
            StartupState.Degraded => "A conversa abriu em modo de recuperação.",
            StartupState.Failed => "Não foi possível concluir a inicialização.",
            StartupState.ShuttingDown => "Encerrando com segurança…",
            _ => "Preparando…"
        };
        _product?.NotifyStartupState(wire);
    }

    private static string ToWireState(StartupState state) => state switch
    {
        StartupState.LoadingHost => "loading_host",
        StartupState.LoadingWebView => "loading_webview",
        StartupState.LoadingShell => "loading_shell",
        StartupState.StartingBridge => "starting_bridge",
        StartupState.ShuttingDown => "shutting_down",
        _ => state.ToString().ToLowerInvariant()
    };

    private void ShowLoading(string message)
    {
        _status.Text = message;
        _actions.Controls.Clear();
        _actions.Visible = false;
        _startup.Visible = true;
        _startup.BringToFront();
    }

    private void ShowFailure(Exception error)
    {
        if (_closing) return;
        _startup.Visible = true;
        _startup.BringToFront();
        _status.Text = error is TimeoutException
            ? "A inicialização demorou mais que o esperado."
            : "Não foi possível abrir o Intent OS.";
        _actions.Controls.Clear();
        _actions.Controls.Add(ActionButton("Tentar novamente", async (_, _) => await RetryAsync(false)));
        _actions.Controls.Add(ActionButton("Modo seguro", async (_, _) => await RetryAsync(true)));
        _actions.Controls.Add(ActionButton("Limpar cache", async (_, _) => await ClearCacheAndRetryAsync()));
        _actions.Controls.Add(ActionButton("Abrir diagnóstico", (_, _) => OpenDiagnostics()));
        _actions.Controls.Add(ActionButton("Fechar", (_, _) => Close()));
        _actions.Visible = true;
    }

    private static Button ActionButton(string text, EventHandler handler)
    {
        var button = new Button { AutoSize = true, Text = text, Padding = new Padding(8, 4, 8, 4) };
        button.Click += handler;
        return button;
    }

    private async Task RetryAsync(bool safeMode)
    {
        CleanupRuntime(resetWebView: true);
        await StartAsync(safeMode);
    }

    private async Task ClearCacheAndRetryAsync()
    {
        CleanupRuntime(resetWebView: true);
        try
        {
            var cache = Path.GetFullPath(_paths.WebViewData);
            var data = Path.GetFullPath(_paths.DataRoot) + Path.DirectorySeparatorChar;
            if (!cache.StartsWith(data, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("O cache não pertence à área de dados do Intent OS.");
            if (Directory.Exists(cache)) Directory.Delete(cache, true);
            Directory.CreateDirectory(cache);
            AppLog.Event("webview_cache_cleared");
            await StartAsync(_safeMode);
        }
        catch (Exception ex) { ShowFailure(ex); }
    }

    private void OpenDiagnostics()
    {
        try { Process.Start(new ProcessStartInfo("explorer.exe", _paths.Logs) { UseShellExecute = true }); }
        catch (Exception ex) { AppLog.Write($"open-diagnostics-failure type={ex.GetType().Name}"); }
    }

    private void CleanupRuntime(bool resetWebView = false)
    {
        if (_product is not null)
        {
            try { _view.CoreWebView2.WebMessageReceived -= _product.HandleMessageAsync; } catch { }
            _product.ForceStop();
            _product = null;
        }
        try { _view.CoreWebView2?.Stop(); } catch { }
        if (resetWebView)
        {
            try { Controls.Remove(_view); _view.Dispose(); } catch { }
            _view = new WebView2 { Dock = DockStyle.Fill, Visible = false };
            Controls.Add(_view);
            _startup.BringToFront();
        }
    }

    private void OnFormClosing(object? sender, FormClosingEventArgs args)
    {
        if (_closing) return;
        _closing = true;
        SetStartupState(StartupState.ShuttingDown);
        AppLog.Event("shutdown_started");
        _startupCancellation.Cancel();
        CleanupRuntime(); // Force-stop is intentionally bounded and non-blocking.
    }

    private void OnFormClosed(object? sender, FormClosedEventArgs args)
    {
        try { _view.Dispose(); } catch { }
        _startupCancellation.Dispose();
        AppLog.Event("shutdown_completed");
    }
}
