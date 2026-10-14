package com.cuckoo.mijia.standalone;

import android.app.*;
import android.content.*;
import android.os.*;
import android.view.*;
import android.webkit.WebView;
import android.widget.Button;
import com.chaquo.python.Python;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.UUID;
import android.webkit.WebChromeClient;
import android.webkit.ConsoleMessage;

/** Invoked only by adb on disposable test devices; never runs automatically. */
public class SmokeInstrumentation extends Instrumentation {
    private String browserError = "";
    private boolean inspectOnly;
    @Override public void onCreate(Bundle args) { super.onCreate(args); inspectOnly=args!=null && "inspect".equals(args.getString("mode")); start(); }

    private void startServer() throws Exception {
        Context context = getTargetContext();
        Intent start = new Intent(context, ServerService.class);
        if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(start); else context.startService(start);
        long deadline = System.currentTimeMillis() + 120000;
        while (!ServerService.ready && System.currentTimeMillis() < deadline) Thread.sleep(250);
        if (!ServerService.ready) throw new AssertionError("Server readiness timeout: " + ServerService.status);
    }

    private View find(View view, Class<?> type, String text) {
        if (type.isInstance(view) && (text == null || ((Button)view).getText().toString().equals(text))) return view;
        if (view instanceof ViewGroup) {
            ViewGroup group=(ViewGroup)view;
            for (int i=0;i<group.getChildCount();i++) {
                View found=find(group.getChildAt(i),type,text);
                if (found!=null) return found;
            }
        }
        return null;
    }

    private void verifyWebView(Activity activity) throws Exception {
        Thread.sleep(1200); // Allow the one-second native readiness indicator to update.
        View root=activity.getWindow().getDecorView();
        runOnMainSync(()->((Button)find(root,Button.class,"打开管理台")).performClick());
        WebView web=(WebView)find(root,WebView.class,null);
        runOnMainSync(()->web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onConsoleMessage(ConsoleMessage message) {
                if (message.messageLevel()==ConsoleMessage.MessageLevel.ERROR) browserError=message.message();
                return true;
            }
        }));
        long deadline=System.currentTimeMillis()+120000;
        while (System.currentTimeMillis()<deadline) {
            AtomicReference<String> body=new AtomicReference<>("");
            CountDownLatch done=new CountDownLatch(1);
            runOnMainSync(()->web.evaluateJavascript("document.body.innerText", value->{body.set(value);done.countDown();}));
            done.await(2,TimeUnit.SECONDS);
            if (body.get().contains("管理员")) return;
            Thread.sleep(250);
        }
        throw new AssertionError("Bundled WebView did not render the administrator form: " + browserError);
    }

    private String javascript(WebView web, String script) throws Exception {
        AtomicReference<String> value=new AtomicReference<>("");
        CountDownLatch done=new CountDownLatch(1);
        runOnMainSync(()->web.evaluateJavascript(script, result->{value.set(result);done.countDown();}));
        if (!done.await(5,TimeUnit.SECONDS)) throw new AssertionError("WebView JavaScript timeout");
        return value.get();
    }

    private void awaitText(WebView web, String text) throws Exception {
        long deadline=System.currentTimeMillis()+60000;
        while (System.currentTimeMillis()<deadline) {
            if (javascript(web,"document.body.innerText").contains(text)) return;
            Thread.sleep(250);
        }
        throw new AssertionError("WebView missing " + text + ": " + browserError);
    }

    private void verifyViewport(WebView web) throws Exception {
        String fits=javascript(web,"document.body.scrollWidth <= document.documentElement.clientWidth + 1");
        if (!"true".equals(fits)) throw new AssertionError("Management console overflows the WebView viewport");
    }

    private void verifyBrowserLogin(Activity activity, String password, Bundle result) throws Exception {
        WebView web=(WebView)find(activity.getWindow().getDecorView(),WebView.class,null);
        runOnMainSync(()->result.putString("webview_user_agent", web.getSettings().getUserAgentString()));
        runOnMainSync(web::reload);
        awaitText(web,"管理员登录");
        verifyViewport(web);
        javascript(web,"(function(){var inputs=document.querySelectorAll('.auth-panel input');"
            +"inputs[0].value='android-smoke';inputs[1].value='"+password+"';"
            +"for(var i=0;i<inputs.length;i++)inputs[i].dispatchEvent(new Event('input',{bubbles:true}));"
            +"var buttons=document.querySelectorAll('.auth-panel button');"
            +"for(var i=0;i<buttons.length;i++)if(buttons[i].innerText.trim()==='登录')buttons[i].click();})()");
        awaitText(web,"设备统计");
        javascript(web,"location.hash='keys'");
        awaitText(web,"创建 API Key");
        javascript(web,"location.hash='devices'");
        awaitText(web,"默认关闭");
        verifyViewport(web);
        result.putString("webview_login_navigation", "passed");
    }

    private void verifyRendererRecovery(MainActivity activity, Bundle result) throws Exception {
        if (Build.VERSION.SDK_INT < 29) { result.putString("renderer_recovery", "unavailable_before_api29"); return; }
        int pid=android.os.Process.myPid(), previous=activity.rendererRecoveries;
        WebView old=(WebView)find(activity.getWindow().getDecorView(),WebView.class,null);
        AtomicReference<Boolean> terminated=new AtomicReference<>(false);
        AtomicReference<Boolean> available=new AtomicReference<>(false);
        runOnMainSync(()->{
            available.set(old.getWebViewRenderProcess()!=null);
            if (available.get()) terminated.set(old.getWebViewRenderProcess().terminate());
        });
        if (!available.get()) { result.putString("renderer_recovery", "in_process_webview"); return; }
        if (!terminated.get()) throw new AssertionError("Renderer fault injection unavailable");
        AtomicReference<WebView> replacement=new AtomicReference<>();
        long deadline=System.currentTimeMillis()+30000;
        while (System.currentTimeMillis()<deadline) {
            runOnMainSync(()->replacement.set((WebView)find(activity.getWindow().getDecorView(),WebView.class,null)));
            if (activity.rendererRecoveries>previous && replacement.get()!=null && replacement.get()!=old) break;
            Thread.sleep(100);
        }
        if (replacement.get()==null || replacement.get()==old) throw new AssertionError("Console was not recreated");
        if (android.os.Process.myPid()!=pid || !ServerService.active || !ServerService.ready) throw new AssertionError("Renderer failure interrupted service");
        runOnMainSync(()->((Button)find(activity.getWindow().getDecorView(),Button.class,"打开管理台")).performClick());
        WebView web=replacement.get();
        deadline=System.currentTimeMillis()+60000;
        while (!javascript(web,"location.href").contains("127.0.0.1:8123") && System.currentTimeMillis()<deadline) Thread.sleep(100);
        javascript(web,"location.hash='keys'");
        awaitText(web,"创建 API Key");
        result.putString("renderer_recovery", "passed");
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context context=getTargetContext();
            Activity activity=startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            startServer();
            verifyWebView(activity);
            if (inspectOnly) {
                result.putString("webview_ui","passed");
                finish(Activity.RESULT_OK,result);
                return;
            }
            String password="Android-ui-"+UUID.randomUUID().toString();
            String before=Python.getInstance().getModule("mijia_android.smoke").callAttr("run",context.getFilesDir().getAbsolutePath()+"/service",password).toString();
            verifyBrowserLogin(activity,password,result);
            verifyRendererRecovery((MainActivity)activity,result);
            context.startService(new Intent(context,ServerService.class).setAction(ServerService.STOP));
            long deadline=System.currentTimeMillis()+15000;
            while (ServerService.active && System.currentTimeMillis()<deadline) Thread.sleep(250);
            if (ServerService.active) throw new AssertionError("Graceful stop timeout");
            Thread.sleep(1000);
            waitForIdleSync();
            startServer();
            String after=Python.getInstance().getModule("mijia_android.smoke").callAttr("verify_restart",context.getFilesDir().getAbsolutePath()+"/service").toString();
            result.putString("smoke",before);
            result.putString("restart",after);
            result.putString("webview_ui","passed");
            finish(Activity.RESULT_OK,result);
        } catch(Throwable error) {
            result.putString("failure",error.getClass().getSimpleName()+": "+error.getMessage());
            android.util.Log.e("MijiaSmoke","Smoke failed",error);
            finish(Activity.RESULT_CANCELED,result);
        }
    }
}
