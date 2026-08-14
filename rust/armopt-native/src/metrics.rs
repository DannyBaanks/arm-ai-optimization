//! Metrics and Evidence - SHA256 signed evidence matching Python format
use anyhow::Result;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::Path;

use crate::contract::{BenchmarkConfig, BenchmarkResult, EvidenceRecord, EngineMode};

/// Write evidence to file with SHA256 signature
pub fn write_evidence(record: &mut EvidenceRecord, path: &Path) -> Result<()> {
    // Serialize without the hash field first - borrow record to avoid move
    let mut json_value = serde_json::to_value(&mut *record)?;
    let json_obj = json_value.as_object_mut().unwrap();
    json_obj.remove("evidence_sha256");
    
    let canonical = serde_json::to_vec(&json_obj)?;
    let hash = Sha256::digest(&canonical);
    let hash_hex = hex::encode(hash);
    
    // Now write the hash back to record
    if let Some(obj) = json_obj.get_mut("evidence_sha256") {
        *obj = serde_json::Value::String(hash_hex.clone());
    } else {
        json_obj.insert("evidence_sha256".to_string(), serde_json::Value::String(hash_hex.clone()));
    }
    
    // Update record with the hash
    record.evidence_sha256 = hash_hex;
    
    // Write full record with hash
    let final_json = serde_json::to_vec_pretty(record)?;
    fs::write(path, final_json)?;
    
    Ok(())
}

/// Verify evidence file integrity
pub fn verify_evidence(path: &Path) -> Result<bool> {
    let content = fs::read_to_string(path)?;
    let mut value: serde_json::Value = serde_json::from_str(&content)?;
    
    // Extract stored hash first (immutable borrow)
    let stored_hash = value.get("evidence_sha256")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    
    // Now mutable borrow to remove hash for canonical computation
    if let Some(obj) = value.as_object_mut() {
        obj.remove("evidence_sha256");
    }
    let canonical = serde_json::to_vec(&value)?;
    let computed_hash = Sha256::digest(&canonical);
    let computed_hex = hex::encode(computed_hash);
    
    Ok(stored_hash == computed_hex)
}

/// Run benchmark for a specific mode with repeats (median)
pub async fn run_benchmark_with_repeats(
    engine: &crate::engine::DemoEngine,
    config: &BenchmarkConfig,
    repeats: usize,
) -> Result<BenchmarkResult> {
    let mut results = Vec::new();
    
    for _ in 0..repeats {
        let result = match config.mode {
            EngineMode::Sequential => engine.run_sequential(config).await?,
            EngineMode::Dataflow => engine.run_dataflow(config).await?,
            _ => anyhow::bail!("run_benchmark_with_repeats does not support EngineMode::Both; use generate_evidence for both modes"),
        };
        results.push(result);
    }
    
    // Return median by wall_ms
    results.sort_by_key(|r| r.wall_ms);
    let median = results[repeats / 2].clone();
    Ok(median)
}

/// Generate complete evidence record for both modes
pub async fn generate_evidence(
    engine: &crate::engine::DemoEngine,
    requests: usize,
    workers: usize,
    repeats: usize,
    workload_id: &str,
) -> Result<EvidenceRecord> {
    let mut record = EvidenceRecord::new("demo-adapter".to_string(), workload_id.to_string());
    
    // Baseline (sequential)
    let baseline_config = BenchmarkConfig {
        requests,
        workers: 1,
        repeats,
        mode: EngineMode::Sequential,
    };
    let baseline = run_benchmark_with_repeats(engine, &baseline_config, repeats).await?;
    record.results.baseline = Some(baseline);
    
    // Optimized (dataflow)
    let dataflow_config = BenchmarkConfig {
        requests,
        workers,
        repeats,
        mode: EngineMode::Dataflow,
    };
    let dataflow = run_benchmark_with_repeats(engine, &dataflow_config, repeats).await?;
    record.results.dataflow = Some(dataflow);
    
    // Compute speedup
    if let (Some(b), Some(d)) = (&record.results.baseline, &record.results.dataflow) {
        record.results.speedup_wall = Some(b.wall_ms as f64 / d.wall_ms as f64);
    }
    record.results.repeats = repeats;
    
    Ok(record)
}