use anyhow::{Context, Result};
use iroh_rpc_client::Client;
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, path::PathBuf};

use iroh_api::{ChunkerConfig, Cid, IpfsPath, Multiaddr, PeerId, DEFAULT_CHUNKS_SIZE};
use iroh_one::config::{Config, CONFIG_FILE_NAME, ENV_PREFIX};
use iroh_rpc_types::Addr;
use iroh_util::{iroh_config_path, make_config};
use tokio::{sync::mpsc, task::JoinHandle, time::Instant};

use crate::service::{self, DEFAULT_SERVICE_SERVER_PORT, RequestTopic};

pub struct Node {
    pub config: Config,
    pub p2p_task: JoinHandle<()>,
    pub store_task: JoinHandle<()>,
}

impl Node {
    pub async fn new(port: u16, server: bool) -> Self {
        let cfg_path = iroh_config_path(CONFIG_FILE_NAME).unwrap();
        let sources = [Some(cfg_path.as_path())];
        let mut config = make_config(
            // default
            Config::default(),
            // potential config files
            &sources,
            // env var prefix for this config
            ENV_PREFIX,
            // map of present command line arguments
            HashMap::<&str, String>::new(),
        )
        .unwrap();

        let store_dir = tempfile::tempdir().unwrap();
        let store_db = store_dir.path().join("store");
        config.store.path = store_db;

        let keystore_db = store_dir.path().join("keystore");
        config.p2p.key_store_path = keystore_db;

        let listening_multiaddrs = vec![
            format!("/ip4/0.0.0.0/tcp/{}", port).parse().unwrap(),
            format!("/ip4/0.0.0.0/udp/{}/quic-v1", port + 1)
                .parse()
                .unwrap(),
        ];

        config.p2p.libp2p.listening_multiaddrs = listening_multiaddrs;
        if server {
            config.p2p.libp2p.bitswap_client = false;
            config.p2p.libp2p.bitswap_server = true;
        } else {
            config.p2p.libp2p.bitswap_client = true;
            config.p2p.libp2p.bitswap_server = false;
        }

        #[cfg(unix)]
        {
            match iroh_util::increase_fd_limit() {
                Ok(soft) => println!("NOFILE limit: soft = {}", soft),
                Err(err) => eprintln!("Error increasing NOFILE limit: {}", err),
            }
        }

        let (store, p2p) = {
            let store_recv = Addr::new_mem();
            let store_sender = store_recv.clone();
            let p2p_recv = Addr::new_mem();
            let p2p_sender = p2p_recv.clone();
            config.rpc_client.store_addr = Some(store_sender);
            config.rpc_client.p2p_addr = Some(p2p_sender);
            config.synchronize_subconfigs();

            let store_rpc = iroh_one::mem_store::start(store_recv, config.store.clone()).await;
            if let Err(store_rpc) = store_rpc {
                eprintln!("Error starting store: {}", store_rpc);
                std::process::exit(1);
            }
            let store_rpc = store_rpc.unwrap();

            let p2p_rpc = iroh_one::mem_p2p::start(p2p_recv, config.p2p.clone())
                .await
                .unwrap();
            (store_rpc, p2p_rpc)
        };

        Self {
            config,
            p2p_task: p2p,
            store_task: store,
        }
    }
}

pub async fn run_server(node: &Node, target_host: String) -> Result<()> {
    println!("starting iroh server");
    let mut api_cfg = iroh_api::config::Config::default();
    api_cfg.rpc_client = node.config.rpc_client.clone();
    let api = iroh_api::Api::new_from_config(api_cfg).await?;
    let path = PathBuf::from("./fixtures/10MiB.car");
    let cid = api
        .add(&path, false, ChunkerConfig::Fixed(DEFAULT_CHUNKS_SIZE))
        .await?;
    println!("cid: {:?}", cid);

    let p2p_rpc = Client::new(node.config.p2p.rpc_client.clone())
        .await?
        .try_p2p()
        .unwrap();
    let (peer_id, addrs) = p2p_rpc
        .get_listening_addrs()
        .await
        .context("getting p2p info")?;

    println!("peer_id: {:?}", peer_id);
    println!("addrs: {:?}", addrs);

    let cid_req = CidRequest {
        cid,
        peer_id,
        addrs,
    };

    let mut service = service::Client::new(target_host.clone()).await;
    let req = service::Request::new(RequestTopic::CidRequest, cid_req.as_bytes());
    service.send(req).await?;
    Ok(())
}

pub async fn run_client(node: &Node) -> Result<()> {
    println!("starting iroh client");
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
            RequestTopic::CidRequest => {
                let cid_req = CidRequest::from_bytes(&request.data)?;
                handle_cid(&cid_req, &node).await?;
            }
            _ => {
                println!("unknown topic: {:?}", request.topic);
                continue;
            }
        }
    }
    Ok(())
}

async fn handle_cid(cid_req: &CidRequest, node: &Node) -> Result<()> {
    let cid = cid_req.cid.clone();
    println!("handling cid: {:?}", cid);
    let mut api_cfg = iroh_api::config::Config::default();
    api_cfg.rpc_client = node.config.rpc_client.clone();
    let api = iroh_api::Api::new_from_config(api_cfg).await?;

    let p2p_rpc = Client::new(node.config.p2p.rpc_client.clone())
        .await?
        .try_p2p()
        .unwrap();
    println!("connecting to peer: {:?}", cid_req.peer_id);

    let current = Instant::now();

    p2p_rpc
        .connect(cid_req.peer_id, cid_req.addrs.clone())
        .await?;
    println!("connected to peer: {:?}", cid_req.peer_id);

    let path = IpfsPath::from_cid(cid.clone());
    let blocks = api.get(&path).unwrap();

    let temp_dir = tempfile::tempdir().unwrap();
    let output = Some(temp_dir.path().join("test.car"));
    let root_path = iroh_api::fs::write_get_stream(&path, blocks, output.as_deref()).await?;
    let duration = current.elapsed();
    println!("done");
    println!("saving file(s) to {}", root_path.to_str().unwrap());
    println!("duration: {:?}", duration);
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
struct CidRequest {
    pub cid: Cid,
    pub peer_id: PeerId,
    pub addrs: Vec<Multiaddr>,
}

impl CidRequest {
    pub fn as_bytes(&self) -> Vec<u8> {
        bincode::serialize(self).expect("failed to serialize")
    }

    pub fn from_bytes(bytes: &[u8]) -> Result<Self> {
        let cidreq = bincode::deserialize(bytes)?;
        Ok(cidreq)
    }
}
