use anyhow::{Result};
use clap::{Parser, Subcommand};

use axum::{
    http::{StatusCode},
    response::IntoResponse,
    routing::{get, get_service},
    Router,
};
use axum_server::tls_rustls::RustlsConfig;
use sendme::{Keypair, PeerId};
use std::{io, net::SocketAddr, path::PathBuf};
use tower_http::{
    services::ServeDir,
    trace::TraceLayer,
};

#[derive(Parser, Debug)]
#[clap(author, version, about, long_about = None)]
struct Args {
    #[clap(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    #[clap(arg_required_else_help = true)]
    HttpServer { tls: u8, serve_path: PathBuf, certs: Option<PathBuf> },
    #[clap(arg_required_else_help = false)]
    HttpClient { target_host: String },
    #[clap(arg_required_else_help = true)]
    PeerID { path: PathBuf },
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> Result<()> {
    let args = Args::parse();
    match args.command {
        Commands::HttpServer { tls, serve_path, certs } => {
            let addr = SocketAddr::from(([0, 0, 0, 0], 443));
            let serve_dir =
                get_service(ServeDir::new(serve_path)).handle_error(handle_error);
            let router = Router::new()
                .route("/foo", get(|| async { "Hi from /foo" }))
                .nest_service("/assets", serve_dir.clone())
                .fallback_service(serve_dir);
            if tls > 0 {
                let cert_path = certs.unwrap();
                let config = RustlsConfig::from_pem_file(
                    cert_path
                        .join("cert.pem"),
                    cert_path
                        .join("key.pem"),
                )
                .await
                .unwrap();
                println!("listening on {} with tls", addr);
                axum_server::bind_rustls(addr, config)
                    .serve(router.layer(TraceLayer::new_for_http()).into_make_service())
                    .await
                    .unwrap();
            } else {
                println!("listening on {}", addr);
                axum::Server::bind(&addr)
                    .serve(router.layer(TraceLayer::new_for_http()).into_make_service())
                    .await
                    .unwrap();
            }
        }
        Commands::HttpClient { target_host } => {
            let body = reqwest::Client::builder()
                .danger_accept_invalid_certs(true)
                .build()
                .unwrap()
                .get(&target_host)
                .send()
                .await?
                .bytes()
                .await?;
            println!("{:?}", body.get(0));
        }
        Commands::PeerID { path } => {
            let keystr = tokio::fs::read(path).await?;
            let keypair = Keypair::try_from_openssh(keystr)?;
            let pid = PeerId::from(keypair.public());
            println!("{}", pid);
        }
    }
    Ok(())
}

async fn handle_error(_err: io::Error) -> impl IntoResponse {
    (StatusCode::INTERNAL_SERVER_ERROR, "Something went wrong...")
}
