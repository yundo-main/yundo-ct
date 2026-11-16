//! 그림판(Rust + Tauri). 그리기와 화면은 `../ui`(웹 화면)가 맡고, 파일 열기·저장 같은
//! 운영체제 기능은 이 Rust 쪽 명령(command)이 맡는다.

use base64::{Engine, engine::general_purpose::STANDARD};
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{Emitter, Manager};

/// `data:image/png;base64,....` 형태의 문자열에서 바이트를 꺼낸다.
pub fn decode_data_url(data_url: &str) -> Result<Vec<u8>, String> {
    let (head, body) = data_url.split_once(',').ok_or("이미지 데이터 형식이 올바르지 않습니다")?;
    if !head.starts_with("data:image/") || !head.ends_with(";base64") {
        return Err("지원하지 않는 이미지 데이터입니다".into());
    }
    STANDARD.decode(body.trim()).map_err(|e| format!("이미지 데이터를 읽을 수 없습니다: {e}"))
}

/// 확장자가 없거나 png가 아니면 `.png`를 붙인다.
pub fn with_png_ext(path: PathBuf) -> PathBuf {
    match path.extension().and_then(|e| e.to_str()).map(str::to_ascii_lowercase) {
        Some(ext) if ext == "png" => path,
        _ => {
            let mut s = path.into_os_string();
            s.push(".png");
            PathBuf::from(s)
        }
    }
}

fn mime_of(path: &Path) -> Option<&'static str> {
    match path.extension()?.to_str()?.to_ascii_lowercase().as_str() {
        "png" => Some("image/png"),
        "jpg" | "jpeg" => Some("image/jpeg"),
        "gif" => Some("image/gif"),
        "bmp" => Some("image/bmp"),
        "webp" => Some("image/webp"),
        _ => None,
    }
}

#[derive(Serialize)]
pub struct Saved {
    pub path: String,
    pub name: String,
}

#[derive(Serialize)]
pub struct Opened {
    pub path: String,
    pub name: String,
    pub data_url: String,
}

fn file_name(path: &Path) -> String {
    path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()
}

/// 저장 위치를 묻고 PNG로 저장한다. 취소하면 `None`.
#[tauri::command]
fn save_png_as(data_url: String, suggested_name: String) -> Result<Option<Saved>, String> {
    let bytes = decode_data_url(&data_url)?;
    let Some(path) = rfd::FileDialog::new()
        .set_title("다른 이름으로 저장")
        .set_file_name(&suggested_name)
        .add_filter("PNG 이미지", &["png"])
        .save_file()
    else {
        return Ok(None);
    };
    let path = with_png_ext(path);
    std::fs::write(&path, bytes).map_err(|e| format!("저장하지 못했습니다: {e}"))?;
    Ok(Some(Saved { name: file_name(&path), path: path.to_string_lossy().into_owned() }))
}

/// 이미 정해진 경로에 그대로 저장한다(Ctrl+S).
#[tauri::command]
fn save_png_to(path: String, data_url: String) -> Result<Saved, String> {
    let bytes = decode_data_url(&data_url)?;
    let path = with_png_ext(PathBuf::from(path));
    std::fs::write(&path, bytes).map_err(|e| format!("저장하지 못했습니다: {e}"))?;
    Ok(Saved { name: file_name(&path), path: path.to_string_lossy().into_owned() })
}

fn read_opened(path: &Path) -> Result<Opened, String> {
    let mime = mime_of(path).ok_or("지원하지 않는 파일 형식입니다")?;
    let bytes = std::fs::read(path).map_err(|e| format!("열지 못했습니다: {e}"))?;
    Ok(Opened {
        name: file_name(path),
        data_url: format!("data:{mime};base64,{}", STANDARD.encode(bytes)),
        path: path.to_string_lossy().into_owned(),
    })
}

/// 이미지 파일을 골라 화면에서 쓸 수 있는 data URL로 돌려준다. 취소하면 `None`.
#[tauri::command]
fn open_image() -> Result<Option<Opened>, String> {
    let Some(path) = rfd::FileDialog::new()
        .set_title("열기")
        .add_filter("이미지", &["png", "jpg", "jpeg", "gif", "bmp", "webp"])
        .pick_file()
    else {
        return Ok(None);
    };
    read_opened(&path).map(Some)
}

/// 파일 브라우저에서 고른 이미지 열기.
#[tauri::command]
fn read_image(path: String) -> Result<Opened, String> {
    read_opened(Path::new(&path))
}

#[derive(Serialize, Debug)]
pub struct Entry {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
}

#[derive(Serialize, Debug)]
pub struct Listing {
    pub path: String,
    pub parent: Option<String>,
    pub entries: Vec<Entry>,
}

const MAX_ENTRIES: usize = 2000;

/// 폴더 안의 하위 폴더와 이미지 파일만 돌려준다(숨김 파일 제외, 폴더 먼저, 이름순).
pub fn list_dir_impl(dir: &Path) -> Result<Listing, String> {
    let read = std::fs::read_dir(dir).map_err(|e| format!("폴더를 열 수 없습니다: {e}"))?;
    let mut entries: Vec<Entry> = read
        .flatten()
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') {
                return None;
            }
            let path = e.path();
            let is_dir = path.is_dir();
            (is_dir || mime_of(&path).is_some()).then(|| Entry { name, path: path.to_string_lossy().into_owned(), is_dir })
        })
        .collect();
    entries.sort_by(|a, b| b.is_dir.cmp(&a.is_dir).then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase())));
    entries.truncate(MAX_ENTRIES);
    Ok(Listing {
        path: dir.to_string_lossy().into_owned(),
        parent: dir.parent().map(|p| p.to_string_lossy().into_owned()),
        entries,
    })
}

fn default_dir() -> PathBuf {
    let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from);
    match home {
        Some(h) if h.join("Pictures").is_dir() => h.join("Pictures"),
        Some(h) => h,
        None => PathBuf::from("."),
    }
}

/// 파일 브라우저: 경로를 주면 그 폴더, 없으면 사진 폴더(또는 홈)를 보여 준다.
#[tauri::command]
fn list_dir(path: Option<String>) -> Result<Listing, String> {
    let dir = path.map(PathBuf::from).unwrap_or_else(default_dir);
    list_dir_impl(&dir)
}

/// 창 닫기 요청 처리. 처음 한 번은 막고(화면이 저장 여부를 묻도록) 이후 요청은 그대로 닫는다.
/// 화면이 응답하지 못하는 경우에도 같은 버튼을 한 번 더 누르면 닫히게 하기 위해서다.
/// 반환값이 true면 닫기를 막는다.
pub fn should_block_close(pending: &AtomicBool) -> bool {
    !pending.swap(true, Ordering::SeqCst)
}

struct CloseState(AtomicBool);

/// 화면이 "닫아도 된다"고 정했을 때 호출한다.
#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

/// 사용자가 닫기를 취소했을 때 호출한다(다음 닫기 요청은 다시 확인을 거친다).
#[tauri::command]
fn close_cancelled(state: tauri::State<CloseState>) {
    state.0.store(false, Ordering::SeqCst);
}

pub fn run() {
    tauri::Builder::default()
        .manage(CloseState(AtomicBool::new(false)))
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let state = window.app_handle().state::<CloseState>();
                if should_block_close(&state.0) {
                    api.prevent_close();
                    let _ = window.emit("close-requested", ());
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            save_png_as, save_png_to, open_image, read_image, list_dir, quit_app, close_cancelled
        ])
        .run(tauri::generate_context!())
        .expect("그림판을 실행하지 못했습니다");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decodes_png_data_url() {
        let url = format!("data:image/png;base64,{}", STANDARD.encode([137, 80, 78, 71]));
        assert_eq!(decode_data_url(&url).unwrap(), vec![137, 80, 78, 71]);
    }

    #[test]
    fn rejects_bad_data_urls() {
        assert!(decode_data_url("no comma").is_err());
        assert!(decode_data_url("data:text/html;base64,AAAA").is_err()); // 이미지가 아님
        assert!(decode_data_url("data:image/png,AAAA").is_err()); // base64가 아님
        assert!(decode_data_url("data:image/png;base64,@@@").is_err());
    }

    #[test]
    fn adds_png_extension_when_missing() {
        assert_eq!(with_png_ext("a/b".into()), PathBuf::from("a/b.png"));
        assert_eq!(with_png_ext("a/b.jpg".into()), PathBuf::from("a/b.jpg.png"));
        assert_eq!(with_png_ext("a/b.PNG".into()), PathBuf::from("a/b.PNG"));
        assert_eq!(with_png_ext("그림.png".into()), PathBuf::from("그림.png"));
    }

    #[test]
    fn lists_only_dirs_and_images_sorted() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path();
        for f in ["b.png", "A.JPG", "notes.txt", ".hidden.png", "c.webp"] {
            std::fs::write(p.join(f), b"x").unwrap();
        }
        std::fs::create_dir(p.join("zeta")).unwrap();
        std::fs::create_dir(p.join("alpha")).unwrap();
        std::fs::create_dir(p.join(".git")).unwrap();
        let l = list_dir_impl(p).unwrap();
        let names: Vec<_> = l.entries.iter().map(|e| (e.name.as_str(), e.is_dir)).collect();
        assert_eq!(names, vec![("alpha", true), ("zeta", true), ("A.JPG", false), ("b.png", false), ("c.webp", false)]);
        assert_eq!(l.parent.as_deref(), p.parent().and_then(|x| x.to_str()));
        assert!(list_dir_impl(&p.join("없는폴더")).is_err());
    }

    #[test]
    fn reads_image_as_data_url_and_rejects_others() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("a.png"), [137u8, 80, 78, 71]).unwrap();
        std::fs::write(dir.path().join("a.txt"), b"hi").unwrap();
        let o = read_opened(&dir.path().join("a.png")).unwrap();
        assert_eq!(o.name, "a.png");
        assert_eq!(decode_data_url(&o.data_url).unwrap(), vec![137, 80, 78, 71]);
        assert!(read_opened(&dir.path().join("a.txt")).is_err());
        assert!(read_opened(&dir.path().join("none.png")).is_err());
    }

    #[test]
    fn close_is_blocked_once_then_allowed() {
        let pending = AtomicBool::new(false);
        assert!(should_block_close(&pending)); // 첫 요청: 막고 화면에 묻는다
        assert!(!should_block_close(&pending)); // 응답이 없어 다시 누르면 닫힌다
        pending.store(false, Ordering::SeqCst); // 사용자가 취소
        assert!(should_block_close(&pending));
    }

    #[test]
    fn mime_by_extension() {
        assert_eq!(mime_of(Path::new("x.JPG")), Some("image/jpeg"));
        assert_eq!(mime_of(Path::new("x.txt")), None);
        assert_eq!(mime_of(Path::new("noext")), None);
    }
}
