#!/usr/bin/env python
# coding=utf-8
# wujian@2018

import argparse
import os
import pickle

import numpy as np
import torch as th
import scipy.io as sio

from utils import stft, istft, parse_scps, apply_cmvn, parse_yaml
from model import PITNet


class Separator(object):
    def __init__(self, nnet, state_dict, cuda=False):
        if not os.path.exists(state_dict):
            raise RuntimeError(
                "Could not find state file {}".format(state_dict))
        self.nnet = nnet

        self.location = "cuda" if args.cuda else "cpu"
        self.nnet.load_state_dict(
            th.load(state_dict, map_location=self.location))
        self.nnet.eval()

    def seperate(self, spectra, cmvn=None):
        """
            spectra: stft complex results T x F
            cmvn: python dict contains global mean/std
        """
        if not np.iscomplexobj(spectra):
            raise ValueError("Input must be matrix in complex value")
        # compute log-magnitude spectrogram
        log_spectra = np.log(np.abs(spectra))
        # apply cmvn or not
        log_spectra = apply_cmvn(log_spectra, cmvn) if cmvn else log_spectra

        out_masks = self.nnet(
            th.tensor(log_spectra, dtype=th.float32, device=self.location),
            train=False)
        spk_masks = [spk_mask.cpu().data.numpy() for spk_mask in out_masks]
        return spk_masks, [spectra * spk_mask for spk_mask in spk_masks]


def run(args):
    num_bins, config_dict = parse_yaml(args.config)
    # Load cmvn
    dict_mvn = config_dict["dataloader"]["mvn_dict"]
    if dict_mvn:
        if not os.path.exists(dict_mvn):
            raise FileNotFoundError("Could not find mvn files")
        with open(dict_mvn, "rb") as f:
            dict_mvn = pickle.load(f)

    dcnet = PITNet(num_bins, **config_dict["model"])

    frame_length = config_dict["spectrogram_reader"]["frame_length"]
    frame_shift = config_dict["spectrogram_reader"]["frame_shift"]
    window = config_dict["spectrogram_reader"]["window"]

    separator = Separator(dcnet, args.state_dict, cuda=args.cuda)

    utt_dict = parse_scps(args.wave_scp)
    num_utts = 0
    for key, utt in utt_dict.items():
        try:
            samps, stft_mat = stft(
                utt,
                frame_length=frame_length,
                frame_shift=frame_shift,
                window=window,
                center=True,
                return_samps=True)
        except FileNotFoundError:
            print("Skip utterance {}... not found".format(key))
            continue
        print("Processing utterance {}".format(key))
        num_utts += 1
        norm = np.linalg.norm(samps, np.inf)
        spk_mask, spk_spectrogram = separator.seperate(stft_mat, cmvn=dict_mvn)

        for index, stft_mat in enumerate(spk_spectrogram):
            istft(
                os.path.join(args.dump_dir, '{}.spk{}.wav'.format(
                    key, index + 1)),
                stft_mat,
                frame_length=frame_length,
                frame_shift=frame_shift,
                window=window,
                center=True,
                norm=norm,
                fs=8000,
                nsamps=samps.size)
            if args.dump_mask:
                sio.savemat(
                    os.path.join(args.dump_dir, '{}.spk{}.mat'.format(
                        key, index + 1)), {"mask": spk_mask[index]})
    print("Processed {} utterance!".format(num_utts))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=
        "Command to seperate single-channel speech using masks clustered on embeddings of DCNet"
    )
    parser.add_argument(
        "config", type=str, help="Location of training configure files")
    parser.add_argument(
        "state_dict", type=str, help="Location of networks state file")
    parser.add_argument(
        "wave_scp",
        type=str,
        help="Location of input wave scripts in kaldi format")
    parser.add_argument(
        "--cuda",
        default=False,
        action="store_true",
        dest="cuda",
        help="If true, inference on GPUs")
    parser.add_argument(
        "--dump-dir",
        type=str,
        default="cache",
        dest="dump_dir",
        help="Location to dump seperated speakers")
    parser.add_argument(
        "--dump-mask",
        default=False,
        action="store_true",
        dest="dump_mask",
        help="If true, dump binary mask matrix")
    args = parser.parse_args()
    run(args)
