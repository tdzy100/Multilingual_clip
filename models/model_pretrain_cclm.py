# Cross-View Language Modeling: Towards Unified Cross-Lingual Cross-Modal Pre-training (https://arxiv.org/abs/2206.00621)
# Github: https://github.com/zengyan-97/CCLM
# Copyright (c) 2022, ByteDance Inc.
# All rights reserved.
import torch
import numpy
from models import XVLMBase
# from multilingual_clip import pt_multilingual_clip
# import transformers
import ipdb
from ipdb import set_trace as st
from clip import clip
from clip.simple_tokenizer import SimpleTokenizer as _Tokenizer

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn.functional as F
import torchvision
from torch import nn
from torchvision import transforms

class CrossViewLM(XVLMBase):
    def __init__(self, config):
        super().__init__(config, load_vision_params=True, load_text_params=True,
                         use_contrastive_loss=True, use_matching_loss=True, use_mlm_loss=True, use_bbox_loss=True, config_text=None)

        self.use_tlm = True if ('use_tlm' in config) and config['use_tlm'] else False

        # device = "cuda" if torch.cuda.is_available() else "cpu"
        self.clip_model, self.preprocess = clip.load("ViT-B/32")
        self.clip_model = self.clip_model.float()
        self.kd_loss = nn.KLDivLoss(size_average=False, reduction="batchmean")

    def get_tlm_loss(self, text_ids_masked, text_atts, masked_pos, masked_ids):
        return self.text_encoder(text_ids_masked,
                          attention_mask=text_atts,
                          encoder_hidden_states=None,
                          encoder_attention_mask=None,
                          return_dict=True,
                          labels=masked_ids,
                          masked_pos=masked_pos).loss

    def forward_multimodal(self, image, text_ids, text_atts, text_ids_masked=None, masked_pos=None, masked_ids=None,
                text_ids_2=None, text_atts_2=None, text_ids_masked_2=None, masked_pos_2=None, masked_ids_2=None,image_clip=None,text_clip=None,
                image_atts=None, idx_to_group_img=None, target_bbox=None, is_image=None, ret_bbox_loss=False):
        
        temp = 1
        text_clip = torch.squeeze(text_clip)
        
        image_clip_all, text_clip_all = self.get_clip_loss(image_clip, text_clip)
        
        with torch.no_grad():
            logits_per_image, logits_per_text = self.clip_model(image_clip_all, text_clip_all)
            prob_clip_image = logits_per_image.softmax(dim=-1)
            prob_clip_text = logits_per_text.softmax(dim=-1)

         
        if ret_bbox_loss:
            image_embeds, image_atts, image_embeds_fullatts = \
                self.get_vision_embeds(image, image_atts=image_atts, idx_to_group_img=idx_to_group_img)
        else:
            image_embeds, image_atts = self.get_vision_embeds(image)

        text_embeds = self.get_text_embeds(text_ids, text_atts)

        with torch.no_grad():
            self.temp.clamp_(0.001, 0.5)
        

        image_feat, text_feat = self.get_features(image_embeds, text_embeds)
        # st()

        loss_i2t, loss_t2i, logits_image, logits_text = self.get_contrastive_loss(image_feat, text_feat)

        prob_xvlm_image = logits_image.softmax(dim=-1)
        prob_xvlm_text = logits_text.softmax(dim=-1)

        loss_itc = (loss_i2t + loss_t2i) / 2

        # st()
        distillation_loss_image = self.kd_loss(
            F.log_softmax(prob_xvlm_image/temp, dim=1),
            F.softmax(prob_clip_image/temp, dim=1)
        )

        distillation_loss_text = self.kd_loss(
            F.log_softmax(prob_xvlm_text/temp, dim=1),
            F.softmax(prob_clip_text/temp, dim=1)
        )

        # loss_itm = self.get_matching_loss(image_embeds, image_atts, image_feat, text_embeds, text_atts, text_feat)
        loss_mlm = self.get_mlm_loss(text_ids_masked, text_atts, image_embeds, image_atts, masked_pos, masked_ids)

        # loss = {'loss_itc': loss_itc, 'loss_itm': loss_itm, 'loss_mlm': loss_mlm}
        loss = {'loss_itc': loss_itc,  'loss_mlm': loss_mlm, 'kd_image': distillation_loss_image, 'kd_text':  distillation_loss_text}

        if ret_bbox_loss:
            output_coord = self.predict_bbox(image_embeds_fullatts, text_embeds, text_atts)
            loss_bbox, loss_giou = self.get_bbox_loss(output_coord, target_bbox, is_image=is_image)

            loss['loss_bbox'] = loss_bbox
            loss['loss_giou'] = loss_giou

        if text_ids_2 is not None:  # multilingual x multimodal
            text_embeds_2 = self.get_text_embeds(text_ids_2, text_atts_2)
            text_feat_2 = self.get_features(text_embeds=text_embeds_2)

            loss_itc_2 = self.get_contrastive_loss(image_feat, text_feat_2)
            #loss_ttc = self.get_contrastive_loss(text_feat, text_feat_2)

            loss['loss_itc'] = (loss['loss_itc'] + loss_itc_2) / 2
            #loss['loss_ttc'] = loss_ttc
            loss['loss_ttc'] = None

            
            # loss_itm_2 = self.get_matching_loss(image_embeds, image_atts, image_feat, text_embeds_2, text_atts_2, text_feat_2)
            # loss['loss_itm'] = (loss['loss_itm'] + loss_itm_2) / 2
            #
            # loss_mlm_2 = self.get_mlm_loss(text_ids_masked_2, text_atts_2, image_embeds, image_atts, masked_pos_2, masked_ids_2)
            # loss['loss_mlm'] = (loss['loss_mlm'] + loss_mlm_2) / 2
            #
            # if ret_bbox_loss:
            #     output_coord_2 = self.predict_bbox(image_embeds_fullatts, text_embeds_2, text_atts_2)
            #     loss_bbox_2, loss_giou_2 = self.get_bbox_loss(output_coord_2, target_bbox, is_image=is_image)
            #     loss['loss_bbox'] = (loss['loss_bbox'] + loss_bbox_2) / 2
            #     loss['loss_giou'] = (loss['loss_giou'] + loss_giou_2) / 2

        return loss

    def forward_para_text(self, text_ids=None, text_atts=None,
                          text_ids_masked=None, text_atts_masked=None, masked_pos=None, masked_ids=None,
                          text_ids_2=None, text_atts_2=None, text_ids_masked_2=None, masked_pos_2=None, masked_ids_2=None):

        text_embeds = self.get_text_embeds(text_ids, text_atts)
        text_embeds_2 = self.get_text_embeds(text_ids_2, text_atts_2)

        with torch.no_grad():
            self.temp.clamp_(0.001, 0.5)

        text_feat = self.get_features(text_embeds=text_embeds)
        text_feat_2 = self.get_features(text_embeds=text_embeds_2)

        if self.use_tlm:
            loss_ttc = self.get_contrastive_loss(text_feat, text_feat_2)
            loss_tlm = self.get_tlm_loss(text_ids_masked, text_atts_masked, masked_pos, masked_ids)
            loss = {'loss_ttc': loss_ttc, 'loss_mlm': loss_tlm}

        else:
            loss_ttc = self.get_contrastive_loss(text_feat, text_feat_2)
            loss_ttm = self.get_matching_loss(text_embeds, text_atts, text_feat, text_embeds_2, text_atts_2, text_feat_2)

            loss_mlm = self.get_mlm_loss(text_ids_masked, text_atts, text_embeds_2, text_atts_2, masked_pos, masked_ids)
            # loss_mlm_2 = self.get_mlm_loss(text_ids_masked_2, text_atts_2, text_embeds, text_atts, masked_pos_2, masked_ids_2)

            loss = {'loss_ttc': loss_ttc, 'loss_ttm': loss_ttm, 'loss_mlm': loss_mlm}

        return loss

    def forward(self, image=None, text_ids=None, text_atts=None,
                text_ids_masked=None, text_atts_masked=None, masked_pos=None, masked_ids=None,
                text_ids_2=None, text_atts_2=None, text_ids_masked_2=None, masked_pos_2=None, masked_ids_2=None, image_clip=None,text_clip=None,
                image_atts=None, idx_to_group_img=None, target_bbox=None, is_image=None, ret_bbox_loss=False):
        
        if image is None:  # parallel text
            # loss = self.forward_para_text(text_ids, text_atts, text_ids_masked, text_atts_masked, masked_pos, masked_ids,
            #               text_ids_2, text_atts_2, text_ids_masked_2, masked_pos_2, masked_ids_2)
            loss = 0

        else:
            
            loss = self.forward_multimodal(image, text_ids, text_atts, text_ids_masked, masked_pos, masked_ids,
                    text_ids_2, text_atts_2, text_ids_masked_2, masked_pos_2, masked_ids_2, image_clip, text_clip,
                    image_atts, idx_to_group_img, target_bbox, is_image, ret_bbox_loss)
            

        return loss
