# ═══════════════════════════════════════════════════════════════════════════
# EXP-031c: 素 FLUX.1-dev コントロール(肌高周波の天井)— ★まっさらな runtime で単独実行
#
#   EXP-031b の C を分離。OOM 原因 = prod stack 解放後も素 FLUX(~34GB)が残メモリに乗らない。
#   → **prod 未ロードの新規 Colab runtime** で本セルだけを実行する(40GB 安全側)。
#
#   ⚠ PuLID 無し = Nika の顔にならない(generic 顔)。これは "FLUX 素の肌の天井" を見る
#      texture baseline であり identity 比較ではない。PO には「顔は別人、見るのは毛穴/グレインだけ」。
#
#   実行(prod 未ロードの新規 runtime で):
#     exec(open("/content/drive/MyDrive/aibo_v7/exp_031c_vanilla_flux.py", encoding="utf-8").read())
# ═══════════════════════════════════════════════════════════════════════════
import os
import torch
from diffusers import FluxPipeline

PROMPT = (
    "close-up portrait photo of a young woman, soft natural daylight, "
    "looking directly at camera, 85mm lens, photorealistic, sharp focus on face"
)
SEED = 12345
W, H = 1024, 1536
STEPS_C = 28
GUIDANCE_C = 3.5
OUT_DIR = "/content/drive/MyDrive/aibo_v7/experiments"
PATH_C = os.path.join(OUT_DIR, "skin_abl_C_vanilla_flux.png")
os.makedirs(OUT_DIR, exist_ok=True)

pipe = FluxPipeline.from_pretrained(
    "black-forest-labs/FLUX.1-dev", torch_dtype=torch.bfloat16
)
pipe.enable_model_cpu_offload()   # 40GB 安全側(.to('cuda') の代わりに OOM 回避)

print(f"[OBS] C vanilla-FLUX | steps={STEPS_C} | guidance={GUIDANCE_C} | "
      f"no-PuLID no-Hyper no-INT4 no-Phase3 | cpu_offload | {W}x{H} | seed={SEED}")
img_c = pipe(
    prompt=PROMPT,
    height=H, width=W,
    num_inference_steps=STEPS_C, guidance_scale=GUIDANCE_C,
    generator=torch.Generator("cuda").manual_seed(SEED),
).images[0]
img_c.convert("RGB").save(PATH_C)
print(f"[exp031c] 保存: {PATH_C}")
print("[exp031c] 完了。PO: 顔は別人(generic)。毛穴/グレインの天井としてのみ A'/B と比較。")
