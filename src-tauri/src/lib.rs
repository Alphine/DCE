use tauri::{Url, WebviewUrl, WebviewWindowBuilder};

/// The DCE web app. The window loads this origin so the API and the
/// SameSite=strict session cookie share one origin (see docs/offline-global.md, section 6).
const APP_URL: &str = "https://commander.basyid.dev";

/// Only the DCE origin may be navigated to inside the window. Anything else
/// (other hosts, http, file, custom schemes) is blocked.
fn is_allowed_navigation(url: &Url, target: &Url) -> bool {
    url.origin() == target.origin()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(|app| {
            let target = Url::parse(APP_URL)?;
            let nav_target = target.clone();

            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(target))
                .title("Disaster Commander Edge")
                .inner_size(1280.0, 800.0)
                .min_inner_size(900.0, 600.0)
                .on_navigation(move |url| is_allowed_navigation(url, &nav_target))
                .build()?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Disaster Commander Edge");
}
