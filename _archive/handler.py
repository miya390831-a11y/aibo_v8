"""
AIBO Studio v8.0 - RunPod Serverless Handler
Entry point for image generation requests
"""
import runpod
import os
import base64
import io
import sys
import traceback
import torch
from PIL import Image

# AIBO コアをインポート
sys.path.insert(0, '/workspace')
from pipeline_manager import PipelineManager

# グローバル: パイプラインを 1 回だけロード (Cold start)
print("[AIBO] Initializing pipeline...")
pipeline_manager = PipelineManager(
    model_path=os.environ.get('MODEL_PATH', '/runpod-volume/models'),
    device='cuda'
)
pipeline = pipeline_manager.get_pipeline()
print("[AIBO] Pipeline ready.")


def handler(event):
    """
    RunPod handler function
    Input: { "input": { "prompt": str, "negative_prompt": str, ... } }
    Output: { "image": base64_str, "metadata": {...} }
    """
    try:
        input_data = event.get('input', {})
        prompt = input_data.get('prompt', '')
        negative_prompt = input_data.get('negative_prompt', '')
        width = input_data.get('width', 1024)
        height = input_data.get('height', 1024)
        steps = input_data.get('steps', 8)  # Hyper-FLUX 8-step
        guidance_scale = input_data.get('guidance_scale', 3.5)
        seed = input_data.get('seed', None)
        
        # PuLID 入力 (顔保存)
        reference_image_b64 = input_data.get('reference_image', None)
        reference_image = None
        if reference_image_b64:
            ref_bytes = base64.b64decode(reference_image_b64)
            reference_image = Image.open(io.BytesIO(ref_bytes))
        
        # 生成実行
        result = pipeline(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            generator=seed and torch.Generator(device='cuda').manual_seed(seed),
            reference_image=reference_image,
        )
        
        image = result.images[0]
        
        # 画像を base64 でエンコード
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        img_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return {
            "image": img_b64,
            "metadata": {
                "prompt": prompt,
                "width": width,
                "height": height,
                "steps": steps,
                "seed": seed,
            },
            "status": "success"
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "status": "failed"
        }


# RunPod serverless 起動
runpod.serverless.start({"handler": handler})
