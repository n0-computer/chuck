use anyhow::{Context, Result};
use bytes::Bytes;
use futures::TryStreamExt;
use iroh_share::{Receiver, Sender, Ticket};
use rand::RngCore;
use std::time::Instant;
use tokio::io::AsyncReadExt;
use tokio::sync::mpsc;

use service::RequestTopic;

use crate::service::{self, DEFAULT_SERVICE_SERVER_PORT};

pub struct MemesyncReceiver {
    port: u16,
}

impl MemesyncReceiver {
    pub async fn new(port: u16) -> Self {
        Self { port }
    }

    pub async fn run(&mut self) -> Result<()> {
        println!("starting memesync receiver");
        let (tx, mut rx) = mpsc::channel(32);
        let mut service =
            service::Server::new(format!("0.0.0.0:{}", DEFAULT_SERVICE_SERVER_PORT), tx).await?;
        tokio::spawn(async move {
            if let Err(e) = service.run().await {
                eprintln!("failed to run service; err = {:?}", e);
            }
        });

        while let Some(request) = rx.recv().await {
            println!("got request");
            match request.topic {
                RequestTopic::MemesyncTicket => {
                    let ticket = Ticket::from_bytes(&request.data)?;
                    self.handle_ticket(&ticket).await?;
                }
                _ => {
                    println!("unknown topic: {:?}", request.topic);
                    continue;
                }
            }
        }
        Ok(())
    }

    pub async fn handle_ticket(&self, ticket: &Ticket) -> Result<()> {
        println!("handling ticket");
        let receiver_dir = tempfile::tempdir().unwrap();
        let receiver_db = receiver_dir.path().join("db");
        let receiver = Receiver::new(self.port, &receiver_db)
            .await
            .context("r: new")
            .unwrap();

        let current = Instant::now();

        let mut receiver_transfer = receiver
            .transfer_from_ticket(ticket)
            .await
            .context("r: transfer")?;

        let data = receiver_transfer.recv().await.context("r: recv")?;
        let files: Vec<_> = data.read_dir()?.unwrap().try_collect().await?;
        let file = &files[0];
        let file_name = file.name.as_ref().unwrap();
        println!("fetching {}", file_name);
        let mut content = Vec::new();
        let file = data.read_file(&files[0]).await?;
        file.pretty()?.read_to_end(&mut content).await?;
        receiver_transfer.finish().await?;
        let duration = current.elapsed();
        println!("bytes: {}", content.len());
        println!("duration: {:?}", duration);
        Ok(())
    }
}

pub struct MemesyncSender {
    target_host: String,
}

impl MemesyncSender {
    pub async fn new(target_host: String) -> Self {
        Self { target_host }
    }

    pub async fn send_file(&mut self, n_bytes: u64, filename: String) -> Result<()> {
        let sender_dir = tempfile::tempdir().unwrap();
        let sender_db = sender_dir.path().join("db");

        let sender = Sender::new(9990, &sender_db).await.context("s:new")?;
        let mut bytes = vec![0u8; n_bytes as usize]; //5 * 1024 * 1024 - 8
        rand::thread_rng().fill_bytes(&mut bytes);
        let bytes = Bytes::from(bytes);

        let sender_transfer = sender
            .transfer_from_data(filename, bytes.clone())
            .await
            .context("s: transfer")?;
        let ticket = sender_transfer.ticket();

        let mut service = service::Client::new(self.target_host.clone()).await;
        let req = service::Request::new(RequestTopic::MemesyncTicket, ticket.as_bytes().to_vec());
        service.send(req).await?;

        println!("waiting for done");
        sender_transfer.done().await?;
        Ok(())
    }
}
