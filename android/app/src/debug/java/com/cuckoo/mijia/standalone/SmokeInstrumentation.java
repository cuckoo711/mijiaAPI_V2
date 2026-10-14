package com.cuckoo.mijia.standalone;

import android.app.*;
import android.content.*;
import android.os.*;
import com.chaquo.python.Python;

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

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context context=getTargetContext();
            startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            startServer();
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
            finish(Activity.RESULT_OK,result);
        } catch(Throwable error) {
            result.putString("failure",error.getClass().getSimpleName()+": "+error.getMessage());
            android.util.Log.e("MijiaSmoke","Smoke failed",error);
            finish(Activity.RESULT_CANCELED,result);
        }
    }
}
