use anyhow::{Context, Result};
use chuck::{iroh, memesync};
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
    MemesyncReceiver { port: u16, sleep: u8 },
    #[clap(arg_required_else_help = true)]
    MemesyncSender {
        target_host: String,
        bytes: u64,
        filename: String,
        sleep: u8,
    },
    #[clap(arg_required_else_help = true)]
    IrohServer { target_host: String },
    #[clap(arg_required_else_help = false)]
    IrohClient {},
    #[clap(arg_required_else_help = true)]
    HttpServer { tls: u8 },
    #[clap(arg_required_else_help = false)]
    HttpClient { target_host: String },
    #[clap(arg_required_else_help = true)]
    PeerID { path: PathBuf },
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> Result<()> {
    let args = Args::parse();
    match args.command {
        Commands::MemesyncReceiver { port, sleep } => {
            let mut receiver = memesync::MemesyncReceiver::new(port).await;
            receiver.run(sleep).await?;
        }
        Commands::MemesyncSender {
            target_host,
            bytes,
            filename,
            sleep,
        } => {
            let mut sender = memesync::MemesyncSender::new(target_host).await;
            sender
                .send_file(bytes, filename, sleep)
                .await
                .context("failed to send file")?;
        }
        Commands::IrohServer { target_host } => {
            let node = iroh::Node::new(4444, true).await;
            iroh::run_server(&node, target_host)
                .await
                .context("failed to run server")?;
        }
        Commands::IrohClient {} => {
            let node = iroh::Node::new(4454, false).await;
            iroh::run_client(&node)
                .await
                .context("failed to run client")?;
        }
        Commands::HttpServer { tls } => {
            let addr = SocketAddr::from(([0, 0, 0, 0], 443));
            let serve_dir =
                get_service(ServeDir::new("/var/lib/netsim")).handle_error(handle_error);
            let router = Router::new()
                .route("/foo", get(|| async { "Hi from /foo" }))
                .nest_service("/assets", serve_dir.clone())
                .fallback_service(serve_dir);
            if tls > 0 {
                let config = RustlsConfig::from_pem_file(
                    PathBuf::from("/var/lib/netsim")
                        .join("self_signed_certs")
                        .join("cert.pem"),
                    PathBuf::from("/var/lib/netsim")
                        .join("self_signed_certs")
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
