package com.cuckoo.mijia.standalone;

import android.Manifest;
import android.app.*;
import android.content.Intent;
import android.content.ActivityNotFoundException;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Insets;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.*;

public class MainActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView status;
    private CheckBox lan;
    private Button start, stop, open;
    private WebView web;
    private boolean pageOpened;
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            status.setText(ServerService.status + (lan.isChecked() ? "\n局域网：" + addresses() : "\n仅允许本机访问"));
            start.setEnabled(!ServerService.active);
            stop.setEnabled(ServerService.active);
            open.setEnabled(ServerService.ready);
            lan.setEnabled(!ServerService.active);
            handler.postDelayed(this, 1000);
        }
    };

    private Button button(LinearLayout parent, String label, View.OnClickListener click) {
        Button button = new Button(this); button.setText(label); button.setOnClickListener(click);
        parent.addView(button, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        return button;
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(47,154,85));
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(244,246,245));
        if (Build.VERSION.SDK_INT >= 35) {
            // Target 35 enforces edge-to-edge; consume bars/cutouts/IME explicitly.
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
            getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                Insets bars=insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                Insets ime=insets.getInsets(WindowInsets.Type.ime());
                view.setPadding(bars.left,bars.top,bars.right,Math.max(bars.bottom,ime.bottom));
                return WindowInsets.CONSUMED;
            });
        } else root.setFitsSystemWindows(true);
        LinearLayout header = new LinearLayout(this); header.setOrientation(LinearLayout.VERTICAL);
        header.setPadding(12,12,12,0); root.addView(header);
        // Keep native header padding out of the WebView's usable viewport.
        TextView title = new TextView(this); title.setText("米家独立服务 · Android 测试版"); title.setTextSize(20); header.addView(title);
        TextView note = new TextView(this); note.setText("第三方非官方应用，与小米无隶属关系。服务、数据库和登录凭据保存在本机，卸载会清除本机数据。");
        note.setTextSize(12); header.addView(note);
        status = new TextView(this); status.setPadding(0,12,0,8); header.addView(status);
        lan = new CheckBox(this); lan.setText("允许局域网访问（仍需管理员或 API Key 鉴权）");
        lan.setChecked(getSharedPreferences("server",MODE_PRIVATE).getBoolean("lan",false));
        lan.setOnCheckedChangeListener((b, value) -> getSharedPreferences("server",MODE_PRIVATE).edit().putBoolean("lan",value).apply());
        header.addView(lan);
        LinearLayout controls = new LinearLayout(this); header.addView(controls);
        start = button(controls, "启动服务", v -> {
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
            Intent intent = new Intent(this, ServerService.class);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent); else startService(intent);
        });
        stop = button(controls, "停止服务", v -> new AlertDialog.Builder(this).setTitle("停止本机服务")
                .setMessage("停止后，本机管理台和局域网 API 暂时不可用。数据会保留。")
                .setNegativeButton("取消",null).setPositiveButton("停止",(d,w) -> startService(new Intent(this,ServerService.class).setAction(ServerService.STOP))).show());
        open = button(controls, "打开管理台", v -> {
            java.util.regex.Matcher chrome = java.util.regex.Pattern.compile("Chrome/(\\d+)").matcher(web.getSettings().getUserAgentString());
            if (chrome.find() && Integer.parseInt(chrome.group(1)) < 49) {
                new AlertDialog.Builder(this).setTitle("请更新系统 WebView")
                        .setMessage("当前系统 WebView 不支持管理台所需的网页功能。请更新 Android System WebView 后再打开。")
                        .setPositiveButton("知道了",null).show();
                return;
            }
            CookieManager.getInstance().setCookie("http://127.0.0.1:8123", "mijia_android_owner=" + ServerService.OWNER_TOKEN + "; Path=/; HttpOnly; SameSite=Strict");
            web.setVisibility(View.VISIBLE);
            if (!pageOpened) { web.loadUrl("http://127.0.0.1:8123/"); pageOpened = true; }
        });
        Button help = new Button(this); help.setText("后台运行帮助");
        help.setOnClickListener(v -> new AlertDialog.Builder(this).setTitle("后台运行")
                .setMessage(backgroundHelp())
                .setPositiveButton("设置后台运行",(d,w)->openBackgroundSettings())
                .setNegativeButton("关闭",null).show());
        header.addView(help);
        web = new WebView(this); web.setVisibility(View.GONE);
        web.getSettings().setJavaScriptEnabled(true); web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false); web.getSettings().setAllowContentAccess(false);
        web.getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptCookie(true);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri=request.getUrl();
                if ("http".equals(uri.getScheme()) && "127.0.0.1".equals(uri.getHost()) && uri.getPort()==8123) return false;
                if ("https".equals(uri.getScheme())) startActivity(new Intent(Intent.ACTION_VIEW,uri));
                return true;
            }
        });
        root.addView(web,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1));
        setContentView(root);
    }

    private String backgroundHelp() {
        PowerManager power=(PowerManager)getSystemService(POWER_SERVICE);
        String state=power.isIgnoringBatteryOptimizations(getPackageName()) ? "已允许不受电池优化限制。" : "尚未解除电池优化限制，长时间锁屏进入休眠后网络可能暂停。";
        return state + "\n\n专用服务手机建议持续供电，并在系统确认中允许持续后台运行。厂商系统可能还需允许自启动或后台活动。退出界面不等于停止服务；强制停止、重启和厂商清理仍会中断。";
    }

    private void openBackgroundSettings() {
        PowerManager power=(PowerManager)getSystemService(POWER_SERVICE);
        Intent intent=power.isIgnoringBatteryOptimizations(getPackageName())
                ? new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                : new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:"+getPackageName()));
        try { startActivity(intent); }
        catch (ActivityNotFoundException | SecurityException unavailable) {
            try { startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:"+getPackageName()))); }
            catch (ActivityNotFoundException | SecurityException ignored) {
                new AlertDialog.Builder(this).setTitle("后台运行设置").setMessage("请打开系统设置，找到本应用的电池或后台运行选项，并允许持续后台运行。")
                        .setPositiveButton("知道了",null).show();
            }
        }
    }

    private String addresses() {
        ArrayList<String> result=new ArrayList<>();
        try {
            for (NetworkInterface ni: Collections.list(NetworkInterface.getNetworkInterfaces()))
                for (InetAddress ip: Collections.list(ni.getInetAddresses()))
                    if (ip instanceof Inet4Address && !ip.isLoopbackAddress()) result.add("http://"+ip.getHostAddress()+":8123");
        } catch (Exception ignored) { }
        return result.isEmpty() ? "未发现 IPv4 地址，请连接 Wi-Fi" : android.text.TextUtils.join("，",result);
    }
    @Override protected void onResume() { super.onResume(); handler.post(refresh); }
    @Override protected void onPause() { handler.removeCallbacks(refresh); CookieManager.getInstance().flush(); super.onPause(); }
    @Override public void onBackPressed() {
        if (web.getVisibility()==View.VISIBLE) { web.setVisibility(View.GONE); } else super.onBackPressed();
    }
    @Override protected void onDestroy() { handler.removeCallbacks(refresh); web.destroy(); super.onDestroy(); }
}
