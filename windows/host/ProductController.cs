using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Web.WebView2.Core;

namespace IntentOS.WindowsHost;

internal sealed record ConversationItem(
    [property: JsonPropertyName("role")] string Role,
    [property: JsonPropertyName("content")] string Content,
    [property: JsonPropertyName("timestamp")] string Timestamp,
    [property: JsonPropertyName("status")] string Status = "concluído",
    [property: JsonPropertyName("provider")] string Provider = "");
internal sealed class ProductState
{
    public string SchemaVersion { get; set; } = "1.2";
    public bool OnboardingComplete { get; set; }
    public string Mode { get; set; } = "real";
    public string Locale { get; set; } = "pt-BR";
    public string Provider { get; set; } = "";
    public string ProviderStatus { get; set; } = "não configurado";
    public Dictionary<string, string> ProviderStates { get; set; } = new()
    {
        ["openai"] = "não configurado",
        ["gemini"] = "não configurado",
    };
    public bool AllowFallback { get; set; }
    public string? LastProviderTest { get; set; }
    public string Theme { get; set; } = "system";
    public string Ambient { get; set; } = "neutral";
    public string Density { get; set; } = "comfortable";
    public bool ReducedMotion { get; set; }
    public List<ConversationItem> History { get; set; } = [];
}

internal sealed class ProductController : IDisposable
{
    internal const string ProtocolVersion = "1.0";
    private readonly AppPaths _paths;
    private readonly CoreWebView2 _web;
    private readonly string _stateFile;
    private ProductState _state;
    private KernelBridge? _bridge;
    private string _bridgeState = "not_started";
    private string? _bridgeDiagnostic;
    private readonly bool _safeMode;
    private readonly SemaphoreSlim _bridgeLifecycle = new(1, 1);
    private CancellationTokenSource _lifetime = new();
    private JsonElement? _lastFlowTrace;
    private string? _lastFunctionalError;
    private string _renderStatus = "not_started";
    private string _migrationStatus = "not_started";

    internal ProductController(AppPaths paths, CoreWebView2 web, bool safeMode = false)
    {
        _paths = paths;
        _web = web;
        _stateFile = Path.Combine(paths.Preferences, "product.json");
        _safeMode = safeMode;
        _state = safeMode ? new ProductState { Mode = "demo" } : LoadState();
        EnsureProviderStates();
    }

    internal async Task<bool> InitializeAsync(CancellationToken cancellationToken = default)
    {
        if (_safeMode)
        {
            _bridgeState = "degraded";
            NotifyStartupState("degraded");
            return false;
        }
        return await TryStartBridgeAsync(cancellationToken);
    }

    internal void NotifyStartupState(string state)
    {
        try { _web.PostWebMessageAsJson(JsonSerializer.Serialize(new { @event = "startup_state", state })); }
        catch (Exception ex) { AppLog.Write($"startup-notify-failure type={ex.GetType().Name}"); }
    }

    internal async void HandleMessageAsync(object? sender, CoreWebView2WebMessageReceivedEventArgs args)
    {
        string requestId = "";
        try
        {
            using var document = JsonDocument.Parse(args.WebMessageAsJson);
            var root = document.RootElement;
            requestId = root.TryGetProperty("requestId", out var id) ? id.GetString() ?? "" : "";
            var action = root.GetProperty("action").GetString() ?? "";
            if (!ClientVersionCompatible(root))
            {
                Reply(requestId, new { ok = false,
                    error = "A interface instalada não é compatível com o núcleo do Intent OS.",
                    errorCode = "version_mismatch", expectedAppVersion = Program.Version,
                    expectedProtocolVersion = ProtocolVersion });
                return;
            }
            object result = action switch
            {
                "get_state" => PublicState(),
                "save_preferences" => SavePreferences(root),
                "complete_onboarding" => CompleteOnboarding(root),
                "explore_demo" => EnterDemo(),
                "exit_demo" => ExitDemo(),
                "connect_provider" => await ConnectProviderAsync(root),
                "test_provider" => await TestProviderAsync(root),
                "disconnect_provider" => DisconnectProvider(root),
                "set_default_provider" => await SetDefaultProviderAsync(root),
                "set_fallback" => SetFallback(root),
                "chat" => await ChatAsync(root),
                "clear_history" => ClearHistory(),
                "diagnostics" => Diagnostics(),
                "restart_bridge" => await RestartBridgeForUser(),
                "open_diagnostics" => OpenDiagnostics(),
                "ui_response_rendered" => MarkRendered(root),
                _ => new { ok = false, error = "Ação não reconhecida." },
            };
            Reply(requestId, result);
        }
        catch (Exception ex)
        {
            AppLog.Write($"request-failure type={ex.GetType().Name} bridgeState={_bridgeState}");
            StopBridge("failed");
            Reply(requestId, new { ok = false,
                error = "Não foi possível iniciar o núcleo do Intent OS.",
                errorCode = "bridge_unavailable", canRetry = true,
                bridgeState = _bridgeState,
                diagnostic = $"bridge_unavailable/{ex.GetType().Name}" });
        }
    }

    private object CompleteOnboarding(JsonElement root)
    {
        ApplyPreferences(root);
        _state.OnboardingComplete = true;
        _state.Mode = _state.ProviderStatus == "conectado" ? "real" : "demo";
        SaveState();
        return new { ok = true, state = PublicState() };
    }

    private object SavePreferences(JsonElement root)
    {
        ApplyPreferences(root);
        SaveState();
        return new { ok = true, state = PublicState() };
    }

    private void ApplyPreferences(JsonElement root)
    {
        if (!root.TryGetProperty("preferences", out var preferences)) return;
        if (preferences.TryGetProperty("locale", out var locale)) _state.Locale = locale.GetString() ?? "pt-BR";
        if (preferences.TryGetProperty("theme", out var theme)) _state.Theme = theme.GetString() ?? "system";
        if (preferences.TryGetProperty("ambient", out var ambient)) _state.Ambient = ambient.GetString() ?? "neutral";
        if (preferences.TryGetProperty("density", out var density)) _state.Density = density.GetString() ?? "comfortable";
        if (preferences.TryGetProperty("reducedMotion", out var motion)) _state.ReducedMotion = motion.GetBoolean();
    }

    private object EnterDemo() { _state.Mode = "demo"; SaveState(); return new { ok = true, state = PublicState() }; }
    private object ExitDemo() { _state.Mode = "real"; SaveState(); return new { ok = true, state = PublicState() }; }

    private async Task<object> ConnectProviderAsync(JsonElement root)
    {
        var provider = root.GetProperty("provider").GetString() ?? "";
        if (provider is not ("openai" or "gemini")) return new { ok = false, error = "Provider não suportado." };
        var key = root.GetProperty("apiKey").GetString()?.Trim() ?? "";
        if ((provider == "openai" && !key.StartsWith("sk-", StringComparison.Ordinal)) || key.Length < 20)
            return new { ok = false, error = $"A chave {ProviderLabel(provider)} informada não parece válida." };

        var protectedBytes = ProtectedData.Protect(Encoding.UTF8.GetBytes(key), null, DataProtectionScope.CurrentUser);
        File.WriteAllBytes(SecretFile(provider), protectedBytes);
        _state.ProviderStates[provider] = "conectando";
        if (string.IsNullOrEmpty(_state.Provider)) _state.Provider = provider;
        SyncDefaultStatus();
        SaveState();
        await TryStartBridgeAsync(_lifetime.Token);
        var test = await TestProviderAsync(provider);
        return test;
    }

    private Task<object> TestProviderAsync(JsonElement root)
    {
        var provider = root.TryGetProperty("provider", out var value) ? value.GetString() ?? _state.Provider : _state.Provider;
        return TestProviderAsync(provider);
    }

    private async Task<object> TestProviderAsync(string provider)
    {
        if (string.IsNullOrEmpty(provider) || !File.Exists(SecretFile(provider)))
            return new { ok = false, state = PublicState(), error = "Este Provider não possui uma chave configurada." };
        try
        {
            using var response = await RequestBridgeAsync(new { action = "test_provider", provider }, true);
            var ok = response.RootElement.GetProperty("ok").GetBoolean();
            var status = response.RootElement.TryGetProperty("status", out var statusValue)
                ? statusValue.GetString() ?? "error" : ok ? "connected" : "error";
            _state.ProviderStates[provider] = TranslateStatus(status);
            _state.LastProviderTest = DateTimeOffset.Now.ToString("O");
            if (ok) { _state.Mode = "real"; if (string.IsNullOrEmpty(_state.Provider)) _state.Provider = provider; }
            SyncDefaultStatus();
            SaveState();
            return new { ok, state = PublicState(), error = ok ? null : ProviderError(provider, status) };
        }
        catch
        {
            _state.ProviderStates[provider] = "erro";
            _state.LastProviderTest = DateTimeOffset.Now.ToString("O");
            SyncDefaultStatus();
            SaveState();
            return new { ok = false, state = PublicState(), error = $"Falha ao validar {ProviderLabel(provider)}." };
        }
    }

    private object DisconnectProvider(JsonElement root)
    {
        var provider = root.TryGetProperty("provider", out var value) ? value.GetString() ?? _state.Provider : _state.Provider;
        StopBridge("stopped");
        if (File.Exists(SecretFile(provider))) File.Delete(SecretFile(provider));
        _state.ProviderStates[provider] = "não configurado";
        if (_state.Provider == provider)
            _state.Provider = ConnectedProviders().FirstOrDefault() ?? "";
        SyncDefaultStatus(); _state.Mode = "real";
        SaveState();
        return new { ok = true, state = PublicState() };
    }

    private async Task<object> SetDefaultProviderAsync(JsonElement root)
    {
        var provider = root.GetProperty("provider").GetString() ?? "";
        if (!_state.ProviderStates.TryGetValue(provider, out var status) || status != "conectado")
            return new { ok = false, state = PublicState(), error = "Conecte e valide este Provider antes de torná-lo padrão." };
        _state.Provider = provider; SyncDefaultStatus(); SaveState();
        await TryStartBridgeAsync(_lifetime.Token);
        return new { ok = true, state = PublicState() };
    }

    private object SetFallback(JsonElement root)
    {
        _state.AllowFallback = root.GetProperty("allowFallback").GetBoolean();
        SaveState();
        return new { ok = true, state = PublicState() };
    }

    private async Task<object> ChatAsync(JsonElement root)
    {
        var message = root.GetProperty("message").GetString()?.Trim() ?? "";
        if (message.Length == 0) return new { ok = false, error = "Escreva uma mensagem antes de enviar." };
        if (_state.Mode == "demo")
        {
            var demo = "Estou no modo demonstração. Posso apresentar a interface, mas não estou conectado a uma IA real.";
            AddTurn(message, demo, "demonstração");
            return new { ok = true, text = demo, provider = "demonstração", state = PublicState() };
        }
        if (_state.ProviderStatus != "conectado")
            return new { ok = false, error = "Conecte um Provider de IA nas Configurações antes de conversar." };

        var history = _state.History.TakeLast(8).Select(x => new { role = x.Role, content = x.Content }).ToArray();
        var fallback = ConnectedProviders().FirstOrDefault(x => x != _state.Provider) ?? "";
        var correlationId = root.TryGetProperty("correlationId", out var correlation)
            ? correlation.GetString() ?? Guid.NewGuid().ToString() : Guid.NewGuid().ToString();
        AppLog.Event("ui_request_created", $"correlation_id={correlationId}");
        var resumeMissionId = root.TryGetProperty("resumeMissionId", out var resume)
            ? resume.GetString() : null;
        JsonDocument response;
        try
        {
            response = await RequestBridgeAsync(new { action = "chat", message, history,
                session_id = "product-alpha", allow_fallback = _state.AllowFallback,
                fallback_provider = fallback, correlation_id = correlationId,
                resume_mission_id = resumeMissionId }, false);
        }
        catch (BridgeRecoveredException)
        {
            return new { ok = false, error = "O núcleo foi reiniciado. Tente enviar novamente.",
                errorCode = "bridge_recovered", canRetry = true, bridgeState = _bridgeState,
                diagnostic = "bridge_recovered/request_cancelled", state = PublicState() };
        }
        using (response)
        {
        if (response.RootElement.TryGetProperty("trace", out var trace))
        {
            _lastFlowTrace = trace.Clone();
            if (trace.TryGetProperty("dataMigrationStatus", out var migration))
                _migrationStatus = migration.GetString() ?? _migrationStatus;
        }
        if (!response.RootElement.GetProperty("ok").GetBoolean())
        {
            if (response.RootElement.TryGetProperty("provider_status", out var providerStatus))
            {
                var failedProvider = response.RootElement.TryGetProperty("provider", out var failedBy)
                    ? failedBy.GetString() ?? _state.Provider : _state.Provider;
                _state.ProviderStates[failedProvider] = TranslateStatus(providerStatus.GetString() ?? "error");
                SyncDefaultStatus(); SaveState();
            }
            _lastFunctionalError = response.RootElement.GetProperty("error").GetString();
            _renderStatus = "error_ready";
            return new { ok = false, error = _lastFunctionalError,
                errorCode = response.RootElement.TryGetProperty("error_code", out var code) ? code.GetString() : "mission_execution",
                missionId = response.RootElement.TryGetProperty("mission_id", out var failedMission) ? failedMission.GetString() : null,
                correlationId, diagnostic = _lastFlowTrace };
        }
        var text = response.RootElement.GetProperty("text").GetString() ?? "";
        var usedProvider = response.RootElement.TryGetProperty("provider", out var producedBy)
            ? producedBy.GetString() ?? _state.Provider : _state.Provider;
        AddTurn(message, text, "concluído", usedProvider);
        _lastFunctionalError = null;
        _renderStatus = "pending";
        return new { ok = true, text, provider = usedProvider,
            providerCalled = response.RootElement.TryGetProperty("provider_called", out var called) && called.GetBoolean(),
            providerExplanation = response.RootElement.TryGetProperty("provider_explanation", out var explanation) ? explanation.GetString() : null,
            missionId = response.RootElement.TryGetProperty("mission_id", out var completedMission) ? completedMission.GetString() : null,
            correlationId, trace = _lastFlowTrace, state = PublicState() };
        }
    }

    private void AddTurn(string user, string assistant, string status, string provider = "")
    {
        var now = DateTimeOffset.UtcNow.ToString("O");
        _state.History.Add(new("user", user, now, status));
        _state.History.Add(new("assistant", assistant, DateTimeOffset.UtcNow.ToString("O"), status, provider));
        if (_state.History.Count > 100) _state.History = _state.History.TakeLast(100).ToList();
        SaveState();
    }

    private object ClearHistory() { _state.History.Clear(); SaveState(); return new { ok = true, state = PublicState() }; }
    private object Diagnostics() => new { ok = true, version = Program.Version, protocolVersion = ProtocolVersion,
        installPath = _paths.InstallRoot,
        dataPath = _paths.DataRoot, kernel = File.Exists(Path.Combine(_paths.InstallRoot, "app", "IntentOS.Bridge.exe")) ? "disponível" : "ausente",
        provider = _state.Provider, providerStates = _state.ProviderStates,
        connected = _state.ProviderStatus == "conectado", bridge = _bridgeState,
        bridgePid = _bridge?.ProcessId, bridgeVersion = _bridge?.BridgeVersion,
        mode = _state.Mode, lastError = _lastFunctionalError ?? _bridgeDiagnostic,
        requestCorrelationId = TraceString("requestCorrelationId"),
        lastCompletedStage = TraceString("lastCompletedStage"),
        lastFailedStage = TraceString("lastFailedStage"), intentId = TraceString("intentId"),
        missionId = TraceString("missionId"), providerCallStarted = TraceBool("providerCallStarted"),
        providerCallCompleted = TraceBool("providerCallCompleted"),
        persistenceStatus = TraceString("persistenceStatus"), renderStatus = _renderStatus,
        dataMigrationStatus = _migrationStatus };

    private object PublicState() => new { onboardingComplete = _state.OnboardingComplete, mode = _state.Mode,
        locale = _state.Locale, provider = _state.Provider, providerStatus = _state.ProviderStatus,
        providerStates = _state.ProviderStates, allowFallback = _state.AllowFallback,
        lastProviderTest = _state.LastProviderTest, theme = _state.Theme, ambient = _state.Ambient,
        density = _state.Density, reducedMotion = _state.ReducedMotion, history = _state.History,
        dataPath = _paths.DataRoot, appVersion = Program.Version, protocolVersion = ProtocolVersion,
        bridgeState = _bridgeState, bridgeReady = _bridgeState == "ready",
        lastError = _lastFunctionalError ?? _bridgeDiagnostic };

    private ProductState LoadState()
    {
        try
        {
            var raw = File.Exists(_stateFile) ? File.ReadAllText(_stateFile, Encoding.UTF8) : null;
            var hasCurrentSchema = false;
            if (raw is not null)
            {
                using var source = JsonDocument.Parse(raw);
                hasCurrentSchema = source.RootElement.TryGetProperty("schemaVersion", out var schema) &&
                    schema.GetString() == "1.2";
            }
            var state = raw is not null
                ? JsonSerializer.Deserialize<ProductState>(raw,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? new()
                : new();
            var normalizedHistory = state.History.Select(item => item with
            { Timestamp = NormalizeTimestamp(item.Timestamp) }).ToList();
            var needsMigration = !hasCurrentSchema || state.SchemaVersion != "1.2" ||
                state.History.Zip(normalizedHistory).Any(pair => pair.First.Timestamp != pair.Second.Timestamp);
            state.History = normalizedHistory;
            state.SchemaVersion = "1.2";
            if (needsMigration && File.Exists(_stateFile))
            {
                var backup = Path.Combine(_paths.DataRoot, "backups",
                    $"product-{DateTimeOffset.UtcNow:yyyyMMdd-HHmmss}.json");
                Directory.CreateDirectory(Path.GetDirectoryName(backup)!);
                File.Copy(_stateFile, backup, true);
                File.WriteAllText(_stateFile, JsonSerializer.Serialize(state,
                    new JsonSerializerOptions { WriteIndented = true,
                        PropertyNamingPolicy = JsonNamingPolicy.CamelCase }), new UTF8Encoding(false));
                _migrationStatus = "completed:migrated=1;isolated=0";
            }
            else _migrationStatus = "completed:migrated=0;isolated=0";
            return state;
        }
        catch (Exception ex)
        {
            try
            {
                var backup = Path.Combine(_paths.Preferences,
                    $"product.invalid-{DateTimeOffset.UtcNow:yyyyMMdd-HHmmss}.json");
                if (File.Exists(_stateFile)) File.Move(_stateFile, backup, true);
                AppLog.Write($"product-state-isolated type={ex.GetType().Name} backup={Path.GetFileName(backup)}");
            }
            catch (Exception backupError) { AppLog.Write($"product-state-isolation-failure type={backupError.GetType().Name}"); }
            return new();
        }
    }
    private void SaveState() => File.WriteAllText(_stateFile,
        JsonSerializer.Serialize(_state, new JsonSerializerOptions
        { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase }),
        new UTF8Encoding(false));

    private object MarkRendered(JsonElement root)
    {
        _renderStatus = root.TryGetProperty("success", out var success) && success.GetBoolean()
            ? "completed" : "failed";
        return new { ok = true };
    }

    private string? TraceString(string name) => _lastFlowTrace is JsonElement trace &&
        trace.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
        ? value.GetString() : null;
    private bool TraceBool(string name) => _lastFlowTrace is JsonElement trace &&
        trace.TryGetProperty(name, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False && value.GetBoolean();
    private static string NormalizeTimestamp(string? value)
    {
        if (DateTimeOffset.TryParse(value, out var parsed)) return parsed.UtcDateTime.ToString("O");
        if (long.TryParse(value, out var unix))
        {
            try { return (Math.Abs(unix) >= 100_000_000_000
                ? DateTimeOffset.FromUnixTimeMilliseconds(unix)
                : DateTimeOffset.FromUnixTimeSeconds(unix)).UtcDateTime.ToString("O"); }
            catch (ArgumentOutOfRangeException) { }
        }
        return DateTimeOffset.UtcNow.ToString("O");
    }
    private string SecretFile(string provider) => Path.Combine(_paths.Preferences, $"provider.{provider}.secret");
    private string UnprotectKey(string provider) => Encoding.UTF8.GetString(ProtectedData.Unprotect(File.ReadAllBytes(SecretFile(provider)), null, DataProtectionScope.CurrentUser));
    private Dictionary<string, string> ProviderKeys() => new[] { "openai", "gemini" }
        .Where(x => File.Exists(SecretFile(x))).ToDictionary(x => x, UnprotectKey);
    private IEnumerable<string> ConnectedProviders() => _state.ProviderStates.Where(x => x.Value == "conectado" && File.Exists(SecretFile(x.Key))).Select(x => x.Key);
    private async Task<bool> TryStartBridgeAsync(CancellationToken cancellationToken = default)
    {
        await _bridgeLifecycle.WaitAsync(cancellationToken);
        try
        {
            StopBridge("starting");
            _bridgeState = "starting";
            _bridgeDiagnostic = null;
            try
            {
                _bridge = await KernelBridge.StartAsync(_paths, ProviderKeys(), _state.Provider, cancellationToken);
                _bridgeState = "ready";
                AppLog.Write($"bridge-ready pid={_bridge.ProcessId} protocol={_bridge.ProtocolVersion} version={_bridge.BridgeVersion}");
                NotifyStartupState("ready");
                return true;
            }
            catch (Exception ex)
            {
                _bridgeState = "failed";
                _bridgeDiagnostic = $"startup/{ex.GetType().Name}";
                AppLog.Write($"bridge-start-failure type={ex.GetType().Name}");
                NotifyStartupState("degraded");
                return false;
            }
        }
        finally { _bridgeLifecycle.Release(); }
    }
    private void StopBridge(string state)
    {
        if (_bridge is not null)
        {
            AppLog.Write($"bridge-stop pid={_bridge.ProcessId} requestedState={state}");
            _bridge.Dispose();
            _bridge = null;
        }
        _bridgeState = state;
    }
    private async Task<JsonDocument> RequestBridgeAsync(object request, bool replayAfterRestart)
    {
        if (_bridge is null || _bridgeState != "ready")
            if (!await TryStartBridgeAsync(_lifetime.Token)) throw new InvalidOperationException("O núcleo não está disponível.");
        try { return await _bridge!.RequestAsync(request); }
        catch (Exception first)
        {
            _bridgeState = "degraded";
            AppLog.Write($"bridge-degraded type={first.GetType().Name}");
            StopBridge("restarting");
            if (!await TryStartBridgeAsync(_lifetime.Token))
            {
                _bridgeState = "unavailable";
                throw new InvalidOperationException("Não foi possível reiniciar o núcleo.", first);
            }
            if (!replayAfterRestart) throw new BridgeRecoveredException();
            try { return await _bridge!.RequestAsync(request); }
            catch (Exception second)
            {
                _bridgeDiagnostic = $"second-failure/{second.GetType().Name}";
                StopBridge("unavailable");
                throw;
            }
        }
    }
    private async Task<object> RestartBridgeForUser() => await TryStartBridgeAsync(_lifetime.Token)
        ? new { ok = true, state = PublicState() }
        : new { ok = false, error = "Não foi possível iniciar o núcleo do Intent OS.",
            errorCode = "bridge_unavailable", canRetry = true, state = PublicState() };
    private object OpenDiagnostics()
    {
        Process.Start(new ProcessStartInfo("explorer.exe", _paths.Logs) { UseShellExecute = true });
        return new { ok = true };
    }
    private static bool ClientVersionCompatible(JsonElement root)
    {
        var app = root.TryGetProperty("uiVersion", out var ui) ? ui.GetString() : Program.Version;
        var protocol = root.TryGetProperty("protocolVersion", out var value) ? value.GetString() : ProtocolVersion;
        return app == Program.Version && protocol == ProtocolVersion;
    }
    private void EnsureProviderStates()
    {
        _state.ProviderStates ??= new();
        foreach (var name in new[] { "openai", "gemini" })
            if (!_state.ProviderStates.ContainsKey(name)) _state.ProviderStates[name] = "não configurado";
        if (!string.IsNullOrEmpty(_state.Provider) && _state.ProviderStatus == "conectado")
            _state.ProviderStates[_state.Provider] = "conectado";
        SyncDefaultStatus();
    }
    private void SyncDefaultStatus() => _state.ProviderStatus = string.IsNullOrEmpty(_state.Provider)
        ? "não configurado" : _state.ProviderStates.GetValueOrDefault(_state.Provider, "não configurado");
    private static string ProviderLabel(string provider) => provider == "gemini" ? "Google Gemini" : "OpenAI";
    private static string TranslateStatus(string status) => status switch
    {
        "connected" => "conectado", "unavailable" => "indisponível",
        "quota_reached" => "limite atingido", "invalid_key" => "erro",
        "provider_error" => "erro", _ => status,
    };
    private static string ProviderError(string provider, string status) => status switch
    {
        "quota_reached" => $"{ProviderLabel(provider)} atingiu o limite disponível.",
        "unavailable" => $"{ProviderLabel(provider)} está temporariamente indisponível.",
        "invalid_key" => $"A chave de {ProviderLabel(provider)} foi recusada.",
        _ => $"A conexão com {ProviderLabel(provider)} não pôde ser validada.",
    };
    private void Reply(string requestId, object result) => _web.PostWebMessageAsJson(
        JsonSerializer.Serialize(new { requestId, result },
            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase }));
    internal void ForceStop()
    {
        try { _lifetime.Cancel(); } catch { }
        StopBridge("stopped");
    }
    public void Dispose()
    {
        ForceStop();
        _bridgeLifecycle.Dispose();
        _lifetime.Dispose();
    }
}

internal sealed class BridgeRecoveredException : Exception;

internal sealed class KernelBridge : IDisposable
{
    private const string ExpectedProtocolVersion = ProductController.ProtocolVersion;
    private const string ExpectedAppVersion = Program.Version;
    private readonly Process _process;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly CancellationTokenSource _lifetime = new();
    private readonly Task _stderrPump;
    internal bool IsRunning => !_process.HasExited;
    internal int ProcessId => _process.Id;
    internal string ProtocolVersion { get; private set; } = "unknown";
    internal string BridgeVersion { get; private set; } = "unknown";
    internal string State { get; private set; } = "not_started";

    private KernelBridge(AppPaths paths, IReadOnlyDictionary<string, string> apiKeys, string defaultProvider)
    {
        var executable = Path.Combine(paths.InstallRoot, "app", "IntentOS.Bridge.exe");
        if (!File.Exists(executable)) throw new FileNotFoundException("A bridge local não foi encontrada.", executable);
        var workingDirectory = Path.GetDirectoryName(executable)
            ?? throw new DirectoryNotFoundException("O diretório da bridge não foi encontrado.");
        if (!Directory.Exists(workingDirectory)) throw new DirectoryNotFoundException(workingDirectory);
        Directory.CreateDirectory(paths.DataRoot);
        var start = new ProcessStartInfo(executable) { UseShellExecute = false, CreateNoWindow = true,
            WorkingDirectory = workingDirectory,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8 };
        if (apiKeys.TryGetValue("openai", out var openaiKey)) start.Environment["OPENAI_API_KEY"] = openaiKey;
        if (apiKeys.TryGetValue("gemini", out var geminiKey)) start.Environment["GEMINI_API_KEY"] = geminiKey;
        start.Environment["INTENTOS_DEFAULT_PROVIDER"] = defaultProvider;
        start.Environment["INTENTOS_DATA_ROOT"] = paths.DataRoot;
        start.Environment["PYTHONUTF8"] = "1";
        State = "starting";
        AppLog.Write($"bridge-start path={executable} workingDirectory={workingDirectory}");
        _process = Process.Start(start) ?? throw new InvalidOperationException("Não foi possível iniciar a bridge local.");
        AppLog.Event("bridge_process_started", $"pid={_process.Id}");
        _stderrPump = PumpStandardErrorAsync(_lifetime.Token);
    }

    internal static async Task<KernelBridge> StartAsync(AppPaths paths,
        IReadOnlyDictionary<string, string> apiKeys, string defaultProvider,
        CancellationToken cancellationToken = default)
    {
        var bridge = new KernelBridge(paths, apiKeys, defaultProvider);
        try
        {
            using var ready = await bridge.ReadDocumentAsync(TimeSpan.FromSeconds(15), "handshake", cancellationToken);
            bridge.ValidateReady(ready.RootElement);
            using var health = await bridge.RequestAsync(new { action = "health" }, cancellationToken);
            bridge.ValidateHealth(health.RootElement);
            bridge.State = "ready";
            AppLog.Write($"bridge-handshake-ready pid={bridge._process.Id} protocol={bridge.ProtocolVersion} version={bridge.BridgeVersion}");
            return bridge;
        }
        catch
        {
            bridge.State = "failed";
            bridge.ForceStop();
            throw;
        }
    }

    internal async Task<JsonDocument> RequestAsync(object request, CancellationToken cancellationToken = default)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            if (_process.HasExited)
                throw new EndOfStreamException($"A bridge encerrou com código {_process.ExitCode}.");
            State = "busy";
            var id = Guid.NewGuid().ToString("N");
            var json = JsonSerializer.Serialize(request);
            using var requestDocument = JsonDocument.Parse(json);
            var fields = requestDocument.RootElement.EnumerateObject().ToDictionary(x => x.Name, x => x.Value.Clone());
            fields["requestId"] = JsonDocument.Parse($"\"{id}\"").RootElement.Clone();
            await _process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(fields).AsMemory(), cancellationToken);
            await _process.StandardInput.FlushAsync(cancellationToken);
            return await ReadDocumentAsync(TimeSpan.FromSeconds(60), "request", cancellationToken);
        }
        catch (Exception ex)
        {
            State = "degraded";
            var exit = _process.HasExited ? _process.ExitCode.ToString() : "running";
            AppLog.Write($"bridge-request-error type={ex.GetType().Name} exitCode={exit}");
            throw;
        }
        finally
        {
            if (State == "busy") State = "ready";
            _gate.Release();
        }
    }

    private async Task<JsonDocument> ReadDocumentAsync(TimeSpan duration, string phase,
        CancellationToken cancellationToken = default)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token, cancellationToken);
        timeout.CancelAfter(duration);
        string? line;
        try { line = await _process.StandardOutput.ReadLineAsync(timeout.Token); }
        catch (OperationCanceledException) when (!_lifetime.IsCancellationRequested)
        { throw new TimeoutException($"A bridge excedeu o tempo limite durante {phase}."); }
        if (line is null) throw new EndOfStreamException($"A bridge encerrou durante {phase}.");
        try { return JsonDocument.Parse(line); }
        catch (JsonException ex) { throw new InvalidDataException($"JSON inválido durante {phase}.", ex); }
    }

    private void ValidateReady(JsonElement root)
    {
        if (!root.TryGetProperty("event", out var eventValue) || eventValue.GetString() != "READY" ||
            !root.TryGetProperty("ready", out var ready) || !ready.GetBoolean())
            throw new InvalidDataException("A bridge não enviou READY.");
        ValidateVersions(root);
    }

    private void ValidateHealth(JsonElement root)
    {
        if (!root.TryGetProperty("ok", out var ok) || !ok.GetBoolean() ||
            !root.TryGetProperty("ready", out var ready) || !ready.GetBoolean() ||
            root.GetProperty("kernel_status").GetString() != "ready" ||
            root.GetProperty("provider_manager_status").GetString() != "ready")
            throw new InvalidDataException("O health check da bridge falhou.");
        ValidateVersions(root);
        AppLog.Write($"bridge-health-ok pid={_process.Id}");
    }

    private void ValidateVersions(JsonElement root)
    {
        ProtocolVersion = root.GetProperty("protocol_version").GetString() ?? "unknown";
        BridgeVersion = root.GetProperty("bridge_version").GetString() ?? "unknown";
        var appVersion = root.GetProperty("app_version").GetString() ?? "unknown";
        if (ProtocolVersion != ExpectedProtocolVersion || appVersion != ExpectedAppVersion || BridgeVersion != ExpectedAppVersion)
            throw new InvalidDataException(
                $"Versão incompatível. Esperado app={ExpectedAppVersion}, protocol={ExpectedProtocolVersion}; " +
                $"encontrado app={appVersion}, bridge={BridgeVersion}, protocol={ProtocolVersion}.");
    }

    private async Task PumpStandardErrorAsync(CancellationToken cancellationToken)
    {
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var line = await _process.StandardError.ReadLineAsync(cancellationToken);
                if (line is null) break;
                // Python diagnostics deliberately contain only exception type and location.
                AppLog.WriteBridge($"python-{line}");
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex) { AppLog.WriteBridge($"stderr-pump-failure type={ex.GetType().Name}"); }
    }

    internal void ForceStop()
    {
        State = "stopped";
        try { _lifetime.Cancel(); } catch { }
        try { if (!_process.HasExited) _process.Kill(true); } catch { }
        string exit;
        try { exit = _process.HasExited ? _process.ExitCode.ToString() : "terminated"; }
        catch { exit = "terminated"; }
        AppLog.Write($"bridge-process-stopped pid={_process.Id} exitCode={exit}");
    }
    public void Dispose()
    {
        ForceStop();
        _process.Dispose(); _gate.Dispose(); _lifetime.Dispose();
    }
}
