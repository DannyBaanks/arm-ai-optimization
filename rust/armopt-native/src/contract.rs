//! JSONL Contract - Must match Python JsonlAdapter exactly
use serde::{Deserialize, Serialize};

/// Request sent to the engine (stdin)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceRequest {
    pub prompt: String,
    pub max_tokens: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub top_p: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stop: Option<Vec<String>>,
}

/// Response returned by the engine (stdout)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceResponse {
    pub text: String,
    pub input_tokens: u32,
    pub output_tokens: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub finish_reason: Option<String>,
}

/// Engine mode
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum EngineMode {
    Sequential,
    Dataflow,
    Both, // For CLI convenience
}

/// Benchmark configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BenchmarkConfig {
    pub requests: usize,
    pub workers: usize,
    pub repeats: usize,
    pub mode: EngineMode,
}

/// Single benchmark run result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BenchmarkResult {
    pub adapter: String,
    pub mode: EngineMode,
    pub requests: usize,
    pub workers: usize,
    pub wall_ms: u64,
    pub mean_latency_ms: f64,
    pub p95_latency_ms: f64,
    pub output_tokens: u32,
    pub tokens_per_second: f64,
    pub repeats: usize,
}

/// Complete evidence record (matches Python evidence schema)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvidenceRecord {
    pub schema: String,
    pub created_at: String,
    pub workload_id: String,
    pub adapter: String,
    pub platform: String,
    pub python: String,
    pub results: EvidenceResults,
    pub evidence_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvidenceResults {
    pub baseline: Option<BenchmarkResult>,
    pub dataflow: Option<BenchmarkResult>,
    pub speedup_wall: Option<f64>,
    pub repeats: usize,
}

impl EvidenceRecord {
    pub fn new(adapter: String, workload_id: String) -> Self {
        use chrono::Utc;
        use std::env;
        Self {
            schema: "armopt.evidence/1".to_string(),
            created_at: Utc::now().to_rfc3339(),
            workload_id,
            adapter,
            platform: format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH),
            python: format!("rust/{}", env!("CARGO_PKG_VERSION")),
            results: EvidenceResults {
                baseline: None,
                dataflow: None,
                speedup_wall: None,
                repeats: 0,
            },
            evidence_sha256: String::new(),
        }
    }
}