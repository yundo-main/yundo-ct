use lecture_server::{build_app, config::Config};

#[tokio::main]
async fn main() {
    let host = std::env::var("HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let port = std::env::var("PORT").unwrap_or_else(|_| "8765".into());
    let addr = format!("{host}:{port}");
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .unwrap_or_else(|e| panic!("{addr} 에 바인딩할 수 없습니다: {e}"));
    println!("강의도구 서버: http://{addr}");
    axum::serve(listener, build_app(Config::from_env())).await.expect("서버 오류");
}
