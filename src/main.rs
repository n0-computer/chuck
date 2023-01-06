use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use chuck::{iroh, memesync};

#[derive(Parser, Debug)]
#[clap(author, version, about, long_about = None)]
struct Args {
    #[clap(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    #[clap(arg_required_else_help = true)]
    MemesyncReceiver { port: u16 },
    #[clap(arg_required_else_help = true)]
    MemesyncSender {
        target_host: String,
        bytes: u64,
        filename: String,
    },
    #[clap(arg_required_else_help = true)]
    IrohServer { target_host: String },
    #[clap(arg_required_else_help = false)]
    IrohClient {},
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> Result<()> {
    let args = Args::parse();
    match args.command {
        Commands::MemesyncReceiver { port } => {
            let mut receiver = memesync::MemesyncReceiver::new(port).await;
            receiver.run().await?;
        }
        Commands::MemesyncSender {
            target_host,
            bytes,
            filename,
        } => {
            let mut sender = memesync::MemesyncSender::new(target_host).await;
            sender
                .send_file(bytes, filename)
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
    }
    iroh_util::block_until_sigint().await;
    Ok(())
}
