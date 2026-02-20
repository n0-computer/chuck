use anyhow::Result;
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio::sync::mpsc;

pub const DEFAULT_SERVICE_SERVER_PORT: u32 = 10001;
pub const DEFAULT_SERVICE_BUFFER_SIZE: usize = 64 * 1024;

pub struct Server {
    listener: TcpListener,
    handler: mpsc::Sender<Request>,
}

impl Server {
    pub async fn new(addr: String, handler: mpsc::Sender<Request>) -> Result<Self, std::io::Error> {
        let listener = TcpListener::bind(&addr).await?;
        Ok(Self { listener, handler })
    }

    pub async fn run(&mut self) -> Result<(), std::io::Error> {
        loop {
            let tx = self.handler.clone();
            let (mut socket, _) = self.listener.accept().await?;
            tokio::spawn(async move {
                let mut buf = [0; DEFAULT_SERVICE_BUFFER_SIZE];
                println!("got connection");
                loop {
                    let n = match socket.read(&mut buf).await {
                        // socket closed
                        Ok(0) => return,
                        Ok(n) => n,
                        Err(e) => {
                            eprintln!("failed to read from socket; err = {:?}", e);
                            return;
                        }
                    };
                    if let Ok(request) = Request::from_bytes(&buf[..n]) {
                        if let Err(e) = tx.send(request).await {
                            eprintln!("failed to send request; err = {:?}", e);
                            return;
                        }
                        let status_ok = "200 OK";
                        if let Err(e) = socket.write_all(status_ok.as_bytes()).await {
                            eprintln!("failed to write to socket; err = {:?}", e);
                            return;
                        }
                    } else {
                        let status_err = "500 Internal Server Error";
                        if let Err(e) = socket.write_all(status_err.as_bytes()).await {
                            eprintln!("failed to write to socket; err = {:?}", e);
                            return;
                        }
                    }
                }
            });
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum RequestTopic {
    MemesyncTicket,
    CidRequest,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Request {
    pub topic: RequestTopic,
    pub data: Vec<u8>,
}

impl Request {
    pub fn new(topic: RequestTopic, data: Vec<u8>) -> Self {
        Self { topic, data }
    }

    pub fn as_bytes(&self) -> Vec<u8> {
        bincode::serialize(self).expect("failed to serialize")
    }

    pub fn from_bytes(bytes: &[u8]) -> Result<Self> {
        let req = bincode::deserialize(bytes)?;
        Ok(req)
    }
}

pub struct Client {
    host: String,
}

impl Client {
    pub async fn new(host: String) -> Self {
        Self { host }
    }

    pub async fn send(&mut self, request: Request) -> Result<(), std::io::Error> {
        let mut socket = tokio::net::TcpStream::connect(&self.host).await?;
        socket.write_all(&request.as_bytes()).await?;
        let mut buf = [0; DEFAULT_SERVICE_BUFFER_SIZE];
        let n = socket.read(&mut buf).await?;
        println!("Response: {}", String::from_utf8_lossy(&buf[..n]));
        Ok(())
    }
}
