export CUDA_VISIBLE_DEVICES=0
# export CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7
python3 run.py --task "pretrain_cclm_3m" --dist "1" --output_dir "/raid/sclu/output/"
