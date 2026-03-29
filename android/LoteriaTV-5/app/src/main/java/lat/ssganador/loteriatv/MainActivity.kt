package lat.ssganador.loteriatv

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject
import java.util.Locale

class MainActivity : AppCompatActivity() {

    private lateinit var wv: WebView

    private val baseUrl = "https://ssganador.lat/"

    private var lastLoadHadError = false
    private var lastFailingUrl: String? = null
    private var networkAvailable = true
    private var lastBridgeInstallUrl: String? = null
    private var lastNativeInfoUrl: String? = null
    private var lastLowMemoryDispatchAt = 0L
    private var retryRunnable: Runnable? = null

    private val cm by lazy { getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager }
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    private fun isErrorUrl(url: String?): Boolean {
        if (url.isNullOrBlank()) return true
        return url.startsWith("chrome-error://") || url.startsWith("about:blank")
    }

    private fun currentMainUrl(): String? = try {
        if (!::wv.isInitialized) null else wv.url
    } catch (_: Throwable) {
        null
    }

    private fun logI(tag: String, msg: String) = PersistentLogger.i(tag, msg)
    private fun logW(tag: String, msg: String) = PersistentLogger.w(tag, msg)
    private fun logE(tag: String, msg: String) = PersistentLogger.e(tag, msg)

    private fun jsQuote(value: String): String = JSONObject.quote(value)

    private fun appVersionName(): String = BuildConfig.VERSION_NAME.ifBlank { "1.0" }

    private fun currentWebViewVersion(): String {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WebView.getCurrentWebViewPackage()?.versionName.orEmpty()
        } else {
            ""
        }
    }

    private fun cancelScheduledRetry() {
        val task = retryRunnable ?: return
        if (::wv.isInitialized) {
            wv.removeCallbacks(task)
        }
        retryRunnable = null
    }

    private fun loadUrlFresh(url: String, reason: String) {
        if (!::wv.isInitialized) return
        logI("LOAD", "loadUrlFresh reason=$reason url=$url")
        val headers = mapOf(
            "Cache-Control" to "no-cache, no-store, max-age=0, must-revalidate",
            "Pragma" to "no-cache",
        )
        wv.loadUrl(url, headers)
    }

    private fun scheduleRetry(url: String, delayMs: Long = 15_000) {
        if (!::wv.isInitialized) return
        cancelScheduledRetry()
        val task = Runnable {
            retryRunnable = null
            if (!networkAvailable) {
                logW("NET", "Sin red, retry pospuesto: $url")
                return@Runnable
            }
            logW("LOAD", "Reintentando: $url")
            lastLoadHadError = false
            loadUrlFresh(url, reason = "scheduled_retry")
        }
        retryRunnable = task
        wv.postDelayed(task, delayMs)
    }

    private fun startNetworkMonitor() {
        if (networkCallback != null) return
        val req = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                networkAvailable = true
                logI("NET", "Red disponible")
                val url = lastFailingUrl ?: baseUrl
                if (lastLoadHadError || isErrorUrl(currentMainUrl())) {
                    logW("NET", "Reintentando por red recuperada: $url")
                    scheduleRetry(url, delayMs = 500)
                }
            }

            override fun onLost(network: Network) {
                networkAvailable = false
                logW("NET", "Red perdida")
            }
        }
        networkCallback = cb
        try {
            cm.registerNetworkCallback(req, cb)
        } catch (t: Throwable) {
            logE("NET", "No se pudo registrar callback: ${t.message}")
        }
    }

    private fun stopNetworkMonitor() {
        val cb = networkCallback ?: return
        try {
            cm.unregisterNetworkCallback(cb)
        } catch (_: Throwable) {
        }
        networkCallback = null
    }

    private fun dispatchLowMemoryToPage(reason: String, trimLevel: String) {
        if (!::wv.isInitialized) return
        val now = System.currentTimeMillis()
        if ((now - lastLowMemoryDispatchAt) < 15_000L) return
        if (lastLoadHadError || isErrorUrl(currentMainUrl())) return

        lastLowMemoryDispatchAt = now
        val js = """
            (function() {
                try {
                    var detail = {
                        message: ${jsQuote(reason)},
                        metadata: {
                            source: "android_native",
                            trim_level: ${jsQuote(trimLevel)},
                            app_version: ${jsQuote(appVersionName())},
                            android_version: ${jsQuote(Build.VERSION.RELEASE ?: "")},
                            webview_version: ${jsQuote(currentWebViewVersion())}
                        }
                    };
                    window.dispatchEvent(new CustomEvent('appLowMemory', { detail: detail }));
                    Android.log('WARN', 'Native low-memory event dispatched: ' + detail.message);
                } catch (e) {
                    try { Android.log('ERROR', 'Native low-memory dispatch failed: ' + e); } catch (_ignored) {}
                }
            })();
        """.trimIndent()
        wv.post { wv.evaluateJavascript(js, null) }
    }

    private fun reportNativeWebViewInfo(view: WebView?, url: String?) {
        val safeView = view ?: return
        val currentUrl = url ?: return
        if (isErrorUrl(currentUrl)) return
        if (lastNativeInfoUrl == currentUrl) return
        lastNativeInfoUrl = currentUrl

        val js = """
            (function() {
                try {
                    window.__NATIVE_APP_INFO__ = {
                        app_version: ${jsQuote(appVersionName())},
                        android_version: ${jsQuote(Build.VERSION.RELEASE ?: "")},
                        webview_version: ${jsQuote(currentWebViewVersion())},
                        device_model: ${jsQuote("${Build.MANUFACTURER} ${Build.MODEL}".trim())}
                    };
                    if (window.DeviceTelemetry && typeof window.DeviceTelemetry.reportWebViewInfo === 'function') {
                        window.DeviceTelemetry.reportWebViewInfo({
                            metadata: window.__NATIVE_APP_INFO__
                        });
                    }
                    Android.log('INFO', 'Native WebView info injected');
                } catch (e) {
                    try { Android.log('ERROR', 'Native WebView info failed: ' + e); } catch (_ignored) {}
                }
            })();
        """.trimIndent()
        safeView.evaluateJavascript(js, null)
    }

    private fun installJsBridgeHooks(view: WebView?, url: String?) {
        val safeView = view ?: return
        val currentUrl = url ?: return
        if (isErrorUrl(currentUrl)) return
        if (lastBridgeInstallUrl == currentUrl) return
        lastBridgeInstallUrl = currentUrl

        safeView.evaluateJavascript(
            """
            (function() {
                if (window.__loggerInstalled) return;
                window.__loggerInstalled = true;
                window.onerror = function(msg, src, line) {
                    try { Android.log('ERROR', 'onerror: ' + msg + ' @ ' + src + ':' + line); } catch (e) {}
                    return false;
                };
                window.addEventListener('unhandledrejection', function(e) {
                    try { Android.log('ERROR', 'UnhandledPromise: ' + (e.reason ? e.reason.toString() : String(e))); } catch (ex) {}
                });
                Android.log('INFO', 'Bridge JS OK');
            })();
            """.trimIndent(),
            null,
        )
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView(webView: WebView) {
        webView.clearCache(false)
        logI("WEBVIEW", "Cache HTTP limpiado (localStorage preservado)")

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            loadsImagesAutomatically = true
            mediaPlaybackRequiresUserGesture = false
            useWideViewPort = true
            loadWithOverviewMode = true
            cacheMode = WebSettings.LOAD_NO_CACHE
            databaseEnabled = true
            builtInZoomControls = false
            displayZoomControls = false
            setSupportZoom(false)
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            allowFileAccess = false
            allowContentAccess = false
            userAgentString = "${userAgentString} LoteriaTV/${appVersionName()}"

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                safeBrowsingEnabled = true
            }
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            webView.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, true)
        }

        webView.setBackgroundColor(0xFF000000.toInt())
        webView.isVerticalScrollBarEnabled = false
        webView.isHorizontalScrollBarEnabled = false

        webView.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(msg: ConsoleMessage?): Boolean {
                val m = msg ?: return false
                val entry = "[${m.sourceId()}:${m.lineNumber()}] ${m.message()}"
                when (m.messageLevel()) {
                    ConsoleMessage.MessageLevel.ERROR -> logE("JS_CONSOLE", entry)
                    ConsoleMessage.MessageLevel.WARNING -> logW("JS_CONSOLE", entry)
                    else -> logI("JS_CONSOLE", entry)
                }
                return true
            }

            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                if (newProgress % 25 == 0) logI("LOAD", "Progreso: $newProgress%")
            }
        }

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url?.toString() ?: return false
                val allowed = url.startsWith("https://ssganador.lat") || url.startsWith("https://api.ssganador.lat")
                if (!allowed) logW("NAV", "URL bloqueada: $url")
                return !allowed
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                cancelScheduledRetry()
                lastLoadHadError = false
                lastFailingUrl = null
                lastBridgeInstallUrl = null
                lastNativeInfoUrl = null
                logI("LOAD", "Iniciando: $url")
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                logI("LOAD", "Cargada: $url")

                if (lastLoadHadError || isErrorUrl(url)) {
                    logW("LOAD", "Saltando JS/LS por error page: url=$url")
                    return
                }

                view?.evaluateJavascript(
                    """
                    (function() {
                        var code = localStorage.getItem('activation_code') || 'SIN_CODIGO';
                        var device = localStorage.getItem('device_id') || 'SIN_DEVICE';
                        Android.log('INFO', 'activation_code=' + code + ' | device_id=' + device);
                        return code + '|' + device;
                    })();
                    """.trimIndent(),
                ) { result ->
                    logI("LS_STATE", "localStorage: $result")
                }

                installJsBridgeHooks(view, url)
                reportNativeWebViewInfo(view, url)
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                if (request?.isForMainFrame != true) return
                lastLoadHadError = true
                lastFailingUrl = request.url?.toString() ?: baseUrl
                val code = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) error?.errorCode else -1
                val desc = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) error?.description else "unknown"
                logE("LOAD", "Error principal: code=$code desc=$desc url=${request.url}")

                if (networkAvailable) {
                    scheduleRetry(lastFailingUrl ?: baseUrl)
                } else {
                    logW("NET", "Sin red, esperando reconexión para reintentar")
                }
            }

            override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) {
                logE("SSL", "Error SSL primaryError=${error?.primaryError}")
                logW("SSL", "HINT: sincronizar reloj del TV Box con NTP")
                handler?.cancel()
            }

            override fun onReceivedHttpError(
                view: WebView?,
                request: WebResourceRequest?,
                errorResponse: WebResourceResponse?,
            ) {
                if (request?.isForMainFrame == true) {
                    val statusCode = errorResponse?.statusCode ?: -1
                    logE("HTTP", "HTTP $statusCode en ${request.url}")
                    if (statusCode >= 500 && networkAvailable) {
                        lastLoadHadError = true
                        lastFailingUrl = request.url?.toString() ?: baseUrl
                        scheduleRetry(lastFailingUrl ?: baseUrl)
                    }
                }
            }

            override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean {
                lastLoadHadError = true
                logE(
                    "WEBVIEW",
                    "Renderer caido: crash=${detail?.didCrash()} priority=${detail?.rendererPriorityAtExit()}",
                )
                rebuildWebView("render_process_gone")
                return true
            }
        }

        webView.removeJavascriptInterface("Android")
        webView.addJavascriptInterface(JsBridge(), "Android")
        logI("WEBVIEW", "Settings OK")
    }

    private fun rebuildWebView(reason: String) {
        if (!::wv.isInitialized) return
        val oldView = wv
        val parent = oldView.parent as? ViewGroup ?: return
        val layoutParams = oldView.layoutParams
        val urlToLoad = lastFailingUrl ?: baseUrl

        cancelScheduledRetry()

        try {
            parent.removeView(oldView)
            oldView.stopLoading()
            oldView.webChromeClient = null
            oldView.webViewClient = null
            oldView.removeJavascriptInterface("Android")
            oldView.destroy()
        } catch (t: Throwable) {
            logW("WEBVIEW", "Destroy previo fallo: ${t.message}")
        }

        val newView = WebView(this)
        newView.id = R.id.webView
        newView.layoutParams = layoutParams
        parent.addView(newView, 0)
        wv = newView

        logW("WEBVIEW", "WebView recreado: $reason")
        configureWebView(wv)
        loadUrlFresh(urlToLoad, reason = "rebuild:$reason")
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        logI("LIFECYCLE", "=== APP INICIADA ===")
        logI("LIFECYCLE", "Dispositivo: ${Build.MANUFACTURER} ${Build.MODEL}")
        logI("LIFECYCLE", "Android: ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT})")
        logI("LIFECYCLE", "APK version: ${appVersionName()} / code=${BuildConfig.VERSION_CODE}")

        setContentView(R.layout.activity_main)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setFullscreenSafe()

        wv = findViewById(R.id.webView)
        configureWebView(wv)

        logI("WEBVIEW", "Cargando: $baseUrl")
        loadUrlFresh(baseUrl, reason = "onCreate")
    }

    inner class JsBridge {
        @JavascriptInterface
        fun log(level: String, msg: String) {
            when (level.uppercase(Locale.US)) {
                "ERROR" -> PersistentLogger.e("JS_BRIDGE", msg)
                "WARN", "WARNING" -> PersistentLogger.w("JS_BRIDGE", msg)
                else -> PersistentLogger.i("JS_BRIDGE", msg)
            }
        }
    }

    override fun onStart() {
        super.onStart()
        logI("LIFECYCLE", "onStart")
        startNetworkMonitor()
    }

    override fun onResume() {
        super.onResume()
        logI("LIFECYCLE", "onResume")
        if (::wv.isInitialized) {
            wv.onResume()
            wv.resumeTimers()
            if (lastLoadHadError || isErrorUrl(currentMainUrl())) {
                scheduleRetry(lastFailingUrl ?: baseUrl, delayMs = 500)
            }
        }
    }

    override fun onPause() {
        super.onPause()
        logI("LIFECYCLE", "onPause")
        if (::wv.isInitialized) {
            wv.onPause()
            wv.pauseTimers()
        }
    }

    override fun onStop() {
        super.onStop()
        logI("LIFECYCLE", "onStop")
        stopNetworkMonitor()
    }

    override fun onDestroy() {
        super.onDestroy()
        logI("LIFECYCLE", "onDestroy")
        stopNetworkMonitor()
        cancelScheduledRetry()
        if (::wv.isInitialized) {
            try {
                wv.stopLoading()
                wv.webChromeClient = null
                wv.webViewClient = null
                wv.removeJavascriptInterface("Android")
                wv.destroy()
            } catch (_: Throwable) {
            }
        }
    }

    override fun onLowMemory() {
        super.onLowMemory()
        logW("SYSTEM", "onLowMemory - RAM critica")
        dispatchLowMemoryToPage("ANDROID_ON_LOW_MEMORY", "ON_LOW_MEMORY")
    }

    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        val desc = when (level) {
            80 -> "TRIM_MEMORY_COMPLETE"
            60 -> "TRIM_MEMORY_MODERATE"
            40 -> "TRIM_MEMORY_BACKGROUND"
            20 -> "TRIM_MEMORY_UI_HIDDEN"
            15 -> "TRIM_MEMORY_RUNNING_CRITICAL"
            10 -> "TRIM_MEMORY_RUNNING_LOW"
            5 -> "TRIM_MEMORY_RUNNING_MODERATE"
            else -> "level=$level"
        }
        logW("SYSTEM", "onTrimMemory: $desc")
        if (level >= 10) {
            dispatchLowMemoryToPage("ANDROID_TRIM_MEMORY", desc)
        }
    }

    private fun setFullscreenSafe() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            window.insetsController?.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
            window.insetsController?.systemBarsBehavior =
                android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                    View.SYSTEM_UI_FLAG_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                )
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) setFullscreenSafe()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        logI("NAV", "Back bloqueado (kiosk)")
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_MENU || keyCode == KeyEvent.KEYCODE_INFO) {
            startActivity(Intent(this, LogViewerActivity::class.java))
            return true
        }
        return super.onKeyDown(keyCode, event)
    }
}
