export CUDA_VISIBLE_DEVICES=4 
python3 run.py --dist 1 --task itr_coco --config configs/cclm-base-ft/Retrieval_coco_en_ft.yaml --output_dir output/coco/coco_en_itr/ --bs 8 --seed 42 --epoch 10 --checkpoint cclm_4m_epoch_29.th
