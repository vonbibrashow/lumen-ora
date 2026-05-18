//! Lumen Ora — Policy Engine Daemon
//!
//! Listens on a Unix domain socket (Linux/macOS) for JSON-RPC tool-call
//! evaluation requests from the Context Shell and Inference Bridge.
//!
//! On Windows the daemon falls back to a TCP listener on 127.0.0.1:8766
//! so that `cargo build` works during development. Ship the Unix-socket
//! path for production (Linux/NixOS target).
//!
//! Protocol (newline-delimited JSON):
//!   Request:  {"jsonrpc":"2.0","id":1,"method":"evaluate","params":{<ToolCall fields>}}
//!   Response: {"jsonrpc":"2.0","id":1,"result":{<PolicyDecision>},"matched_rule":null|"rule-id"}

use policy_engine::{AuditEntry, PolicyEngine, ToolCall};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tracing::{error, info, warn};

// ---------------------------------------------------------------------------
// JSON-RPC wire types
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct RpcRequest {
    #[allow(dead_code)]
    jsonrpc: String,
    id: Value,
    method: String,
    params: Option<Value>,
}

#[derive(Debug, Serialize)]
struct RpcResponse {
    jsonrpc: &'static str,
    id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<RpcError>,
}

#[derive(Debug, Serialize)]
struct RpcError {
    code: i32,
    message: String,
}

impl RpcResponse {
    fn ok(id: Value, result: Value) -> Self {
        RpcResponse { jsonrpc: "2.0", id, result: Some(result), error: None }
    }

    fn err(id: Value, code: i32, message: impl Into<String>) -> Self {
        RpcResponse {
            jsonrpc: "2.0",
            id,
            result: None,
            error: Some(RpcError { code, message: message.into() }),
        }
    }
}

// ---------------------------------------------------------------------------
// Request params
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct EvaluateParams {
    tool_name: String,
    parameters: Value,
    #[serde(default)]
    context: HashMap<String, String>,
}

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

fn dispatch(req: &RpcRequest, engine: &PolicyEngine) -> RpcResponse {
    match req.method.as_str() {
        "evaluate" => {
            let params: EvaluateParams = match req
                .params
                .as_ref()
                .and_then(|p| serde_json::from_value(p.clone()).ok())
            {
                Some(p) => p,
                None => return RpcResponse::err(req.id.clone(), -32602, "Invalid params for evaluate"),
            };

            let tool_call = ToolCall {
                tool_name: params.tool_name,
                parameters: params.parameters,
                context: params.context,
            };

            let entry: AuditEntry = engine.evaluate_with_audit(tool_call);
            let result = serde_json::to_value(&entry).unwrap_or(Value::Null);
            RpcResponse::ok(req.id.clone(), result)
        }

        "ping" => RpcResponse::ok(req.id.clone(), serde_json::json!({ "status": "ok" })),

        "list_rules" => RpcResponse::ok(
            req.id.clone(),
            serde_json::json!({
                "rules": [
                    "path-traversal-deny",
                    "write-outside-home-deny",
                    "raw-ip-network-confirm",
                    "tmp-exec-deny",
                    "bulk-delete-confirm"
                ]
            }),
        ),

        unknown => RpcResponse::err(req.id.clone(), -32601, format!("Method not found: {unknown}")),
    }
}

// ---------------------------------------------------------------------------
// Connection handler (generic over stream type)
// ---------------------------------------------------------------------------

async fn handle_lines<R, W>(mut reader: BufReader<R>, mut writer: W, engine: Arc<PolicyEngine>)
where
    R: tokio::io::AsyncRead + Unpin,
    W: AsyncWriteExt + Unpin,
{
    let mut lines = reader.lines();
    while let Ok(Some(line)) = lines.next_line().await {
        let line = line.trim().to_string();
        if line.is_empty() {
            continue;
        }
        let response = match serde_json::from_str::<RpcRequest>(&line) {
            Err(e) => RpcResponse::err(Value::Null, -32700, format!("Parse error: {e}")),
            Ok(req) => dispatch(&req, &engine),
        };
        let mut out = serde_json::to_string(&response).unwrap_or_default();
        out.push('\n');
        if let Err(e) = writer.write_all(out.as_bytes()).await {
            warn!("Failed to write response: {e}");
            break;
        }
    }
}

// ---------------------------------------------------------------------------
// Platform-specific listeners
// ---------------------------------------------------------------------------

#[cfg(unix)]
async fn run_server(engine: Arc<PolicyEngine>) {
    // If LUMEN_TCP_PORT is set, listen on TCP (for Windows-side dev/test access)
    if let Ok(port) = std::env::var("LUMEN_TCP_PORT") {
        use tokio::net::TcpListener;
        let addr = format!("0.0.0.0:{port}");
        let listener = match TcpListener::bind(&addr).await {
            Ok(l) => l,
            Err(e) => { error!("Failed to bind TCP {addr}: {e}"); std::process::exit(1); }
        };
        info!("Policy Engine listening on TCP {addr} (dev mode)");
        loop {
            match listener.accept().await {
                Ok((stream, _)) => {
                    let eng = Arc::clone(&engine);
                    tokio::spawn(async move {
                        let (r, w) = stream.into_split();
                        handle_lines(BufReader::new(r), w, eng).await;
                    });
                }
                Err(e) => error!("Accept error: {e}"),
            }
        }
    } else {
        use std::path::Path;
        use tokio::net::UnixListener;

        let socket_path = std::env::var("POLICY_ENGINE_SOCKET")
            .unwrap_or_else(|_| "/tmp/lumen-policy.sock".to_string());

        if Path::new(&socket_path).exists() {
            let _ = std::fs::remove_file(&socket_path);
        }

        let listener = match UnixListener::bind(&socket_path) {
            Ok(l) => l,
            Err(e) => {
                error!("Failed to bind Unix socket {socket_path}: {e}");
                std::process::exit(1);
            }
        };
        info!("Policy Engine listening on Unix socket {socket_path}");

        loop {
            match listener.accept().await {
                Ok((stream, _)) => {
                    let eng = Arc::clone(&engine);
                    tokio::spawn(async move {
                        let (r, w) = stream.into_split();
                        handle_lines(BufReader::new(r), w, eng).await;
                    });
                }
                Err(e) => error!("Accept error: {e}"),
            }
        }
    }
}

#[cfg(not(unix))]
async fn run_server(engine: Arc<PolicyEngine>) {
    use tokio::net::TcpListener;

    let addr = std::env::var("POLICY_ENGINE_ADDR")
        .unwrap_or_else(|_| "127.0.0.1:8766".to_string());

    let listener = match TcpListener::bind(&addr).await {
        Ok(l) => l,
        Err(e) => {
            error!("Failed to bind TCP {addr}: {e}");
            std::process::exit(1);
        }
    };
    info!("Policy Engine listening on TCP {addr} (Windows dev mode)");

    loop {
        match listener.accept().await {
            Ok((stream, peer)) => {
                info!("Connection from {peer}");
                let eng = Arc::clone(&engine);
                tokio::spawn(async move {
                    let (r, w) = stream.into_split();
                    handle_lines(BufReader::new(r), w, eng).await;
                });
            }
            Err(e) => error!("Accept error: {e}"),
        }
    }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_env("LUMEN_LOG")
                .add_directive(tracing::Level::INFO.into()),
        )
        .init();

    let engine = Arc::new(PolicyEngine::with_default_rules());
    info!("Lumen Ora Policy Engine starting — {} rules loaded", 5);
    run_server(engine).await;
}
