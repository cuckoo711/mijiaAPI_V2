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

/** Invoked only by adb on disposable test devices; never runs automatically. */
public class SmokeInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }

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
        long deadline=System.currentTimeMillis()+30000;
        while (System.currentTimeMillis()<deadline) {
            AtomicReference<String> body=new AtomicReference<>("");
            CountDownLatch done=new CountDownLatch(1);
            runOnMainSync(()->web.evaluateJavascript("document.body.innerText", value->{body.set(value);done.countDown();}));
            done.await(2,TimeUnit.SECONDS);
            if (body.get().contains("管理员")) return;
            Thread.sleep(250);
        }
        throw new AssertionError("Bundled WebView did not render the administrator form");
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context context=getTargetContext();
            Activity activity=startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            startServer();
            verifyWebView(activity);
            String before=Python.getInstance().getModule("mijia_android.smoke").callAttr("run",context.getFilesDir().getAbsolutePath()+"/service").toString();
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
