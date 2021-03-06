import baseline.data
import numpy as np
from collections import Counter
import re
import codecs


def num_lines(filename):
    lines = 0
    with codecs.open(filename, encoding='utf-8', mode='r') as f:
        for _ in f:
            lines = lines + 1
    return lines


class TSVSentencePairReader:

    @staticmethod
    def build_vocab(colids, files, clean=False, chars=False):
        vocab = Counter()
        vocab['<PAD>'] = 1
        vocab['<GO>'] = 1
        vocab['<EOS>'] = 1
        for file in files:
            if file is None:
                continue
            with codecs.open(file, encoding='utf-8', mode='r') as f:
                for line in f:
                    cols = re.split("\t", line)
                    for col in colids:
                        text = re.split("\s", cols[col])

                        for w in text:
                            w = w.strip()
                            vocab[w] += 1
        return vocab

    @staticmethod
    def load(tsfile, vocab1, vocab2, mxlen, vec_alloc=np.zeros):

        PAD = vocab1['<PADDING>']
        GO = vocab2['<GO>']
        EOS = vocab2['<EOS>']

        ts = []
        with codecs.open(tsfile, encoding='utf-8', mode='r') as f:
            for line in f:
                splits = re.split("\t", line.strip())
                src = re.split("\s+", splits[0])
                dst = re.split("\s+", splits[1])

                srcl = vec_alloc(mxlen, dtype=np.int)
                tgtl = vec_alloc(mxlen, dtype=np.int)
                src_len = len(src)
                tgt_len = len(dst) + 2
                end1 = min(src_len, mxlen)
                end2 = min(tgt_len, mxlen)-2
                last = max(end1, end2)
                tgtl[0] = GO
                src_len = end1
                tgt_len = end2+2

                for j in range(last):
                    idx1 = vocab1[src[j]] if j < end1 else PAD
                    idx2 = vocab2[dst[j]] if j < end2 else PAD
                    srcl[j] = idx1
                    tgtl[j + 1] = idx2

                tgtl[end2] = EOS

                ts.append((srcl, tgtl, src_len, tgt_len))
        return baseline.data.Seq2SeqExamples(ts)

def identity_trans_fn(x):
    return x

class CONLLSeqReader:

    UNREP_EMOTICONS = (
        ':)',
        ':(((',
        ':D',
        '=)',
        ':-)',
        '=(',
        '(=',
        '=[[',
    )

    def __init__(self, max_sentence_length=-1, max_word_length=-1, word_trans_fn=None, vec_alloc=np.zeros, vec_shape=np.shape, trim=False):
        self.cleanup_fn = identity_trans_fn if word_trans_fn is None else word_trans_fn
        self.max_sentence_length = max_sentence_length
        self.max_word_length = max_word_length
        self.vec_alloc = vec_alloc
        self.vec_shape = vec_shape
        self.trim = trim
        self.label2index = {"<PAD>": 0}

    @staticmethod
    def web_cleanup(word):
        if word.startswith('http'): return 'URL'
        if word.startswith('@'): return '@@@@'
        if word.startswith('#'): return '####'
        if word == '"': return ','
        if word in CONLLSeqReader.UNREP_EMOTICONS: return ';)'
        if word == '<3': return '&lt;3'
        return word

    def build_vocab(self, files):
        vocab_word = Counter()
        vocab_ch = Counter()
        maxw = 0
        maxs = 0
        for file in files:
            if file is None:
                continue

            sl = 0
            with codecs.open(file, encoding='utf-8', mode='r') as f:
                for line in f:

                    line = line.strip()
                    if line == '':
                        maxs = max(maxs, sl)
                        sl = 0

                    else:
                        states = re.split("\s", line)
                        sl += 1
                        w = states[0]
                        vocab_word[self.cleanup_fn(w)] += 1
                        maxw = max(maxw, len(w))
                        for k in w:
                            vocab_ch[k] += 1

        self.max_word_length = min(maxw, self.max_word_length) if self.max_word_length > 0 else maxw
        self.max_sentence_length = min(maxs, self.max_sentence_length) if self.max_sentence_length > 0 else maxs
        print('Max sentence length %d' % self.max_sentence_length)
        print('Max word length %d' % self.max_word_length)

        return vocab_ch, vocab_word

    @staticmethod
    def read_lines(tsfile):

        txts = []
        lbls = []
        txt = []
        lbl = []

        with codecs.open(tsfile, encoding='utf-8', mode='r') as f:
            for line in f:
                states = re.split("\s", line.strip())

                if len(states) > 1:
                    txt.append(states[0])
                    lbl.append(states[-1])
                else:
                    txts.append(txt)
                    lbls.append(lbl)
                    txt = []
                    lbl = []


        return txts, lbls

    def load(self, filename, words_vocab, chars_vocab, batchsz, shuffle=False):

        ts = []
        idx = 0
        mxlen = self.max_sentence_length
        maxw = self.max_word_length
        txts, lbls = CONLLSeqReader.read_lines(filename)

        for i in range(len(txts)):

            xs_ch = self.vec_alloc((mxlen, maxw), dtype=np.int)
            xs = self.vec_alloc((mxlen), dtype=np.int)
            ys = self.vec_alloc((mxlen), dtype=np.int)

            lv = lbls[i]
            v = txts[i]

            length = mxlen
            for j in range(mxlen):

                if j == len(v):
                    length = j
                    break

                w = v[j]
                nch = min(len(w), maxw)
                label = lv[j]

                if label not in self.label2index:
                    idx += 1
                    self.label2index[label] = idx

                ys[j] = self.label2index[label]
                xs[j] = words_vocab.get(self.cleanup_fn(w))
                for k in range(nch):
                    xs_ch[j, k] = chars_vocab.get(w[k], 0)

            ts.append((xs, xs_ch, ys, length, i))
        examples = baseline.data.SeqWordCharTagExamples(ts)
        return baseline.data.SeqWordCharLabelDataFeed(examples, batchsz=batchsz, shuffle=shuffle, alloc_fn=self.vec_alloc, shape_fn=self.vec_shape), txts


class TSVSeqLabelReader:

    REPLACE = { "'s": " 's ",
                "'ve": " 've ",
                "n't": " n't ",
                "'re": " 're ",
                "'d": " 'd ",
                "'ll": " 'll ",
                ",": " , ",
                "!": " ! ",
                }

    def __init__(self, mxlen=1000, mxfiltsz=0, clean_fn=None, vec_alloc=np.zeros):
        self.vocab = None
        self.label2index = {}
        self.clean_fn = clean_fn #TSVSeqLabelReader.do_clean
        self.mxlen = mxlen
        self.mxfiltsz = mxfiltsz
        self.vec_alloc=vec_alloc
        if self.clean_fn is None:
            self.clean_fn = lambda x: x

    @staticmethod
    def splits(text):
        return list(filter(lambda s: len(s) != 0, re.split('\s+', text)))

    @staticmethod
    def do_clean(l):
        l = l.lower()
        l = re.sub(r"[^A-Za-z0-9(),!?\'\`]", " ", l)
        for k, v in TSVSeqLabelReader.REPLACE.items():
            l = l.replace(k, v)
        return l.strip()

    @staticmethod
    def label_and_sentence(line, clean_fn):
        label_text = re.split('[\t\s]+', line)
        label = label_text[0]
        text = label_text[1:]
        text = ' '.join(list(filter(lambda s: len(s) != 0, [clean_fn(w) for w in text])))
        return label, text

    def build_vocab(self, files):
        vocab = Counter()
        for file in files:
            if file is None:
                continue
            with codecs.open(file, encoding='utf-8', mode='r') as f:
                for line in f:
                    _, text = TSVSeqLabelReader.label_and_sentence(line, self.clean_fn)
                    for w in TSVSeqLabelReader.splits(text):
                        vocab[w] += 1
        return vocab

    def load(self, filename, index, batchsz, shuffle=False):

        PAD = index['<PADDING>']
        halffiltsz = self.mxfiltsz // 2
        nozplen = self.mxlen - 2*halffiltsz
        label_idx = len(self.label2index)
        examples = []
        with codecs.open(filename, encoding='utf-8', mode='r') as f:
            for offset, line in enumerate(f):
                label, text = TSVSeqLabelReader.label_and_sentence(line, self.clean_fn)
                if label not in self.label2index:
                    self.label2index[label] = label_idx
                    label_idx += 1

                y = self.label2index[label]
                toks = TSVSeqLabelReader.splits(text)
                mx = min(len(toks), nozplen)
                toks = toks[:mx]
                x = self.vec_alloc(self.mxlen, dtype=int)
                for j in range(len(toks)):
                    w = toks[j]
                    key = index.get(w, PAD)
                    x[j+halffiltsz] = key
                examples.append((x, y))
        return baseline.data.SeqLabelDataFeed(baseline.data.SeqLabelExamples(examples),
                                              batchsz=batchsz, shuffle=shuffle, alloc_fn=self.vec_alloc)

class PTBSeqReader:

    @staticmethod
    def build_vocab(files):
        vocab_word = Counter()
        vocab_ch = Counter()
        maxw = 0
        num_words_in_files = []
        for file in files:
            if file is None:
                continue

            with codecs.open(file, encoding='utf-8', mode='r') as f:
                num_words = 0
                for line in f:
                    sentence = line.split() + ['<EOS>']
                    num_words += len(sentence)
                    for w in sentence:
                        vocab_word[w] += 1
                        maxw = max(maxw, len(w))
                        for k in w:
                            vocab_ch[k] += 1
                num_words_in_files.append(num_words)

        return maxw, vocab_ch, vocab_word, num_words_in_files

    @staticmethod
    def load(filename, words_vocab, chars_vocab, num_words, maxw, vec_alloc=np.zeros):

        xch = vec_alloc((num_words, maxw), np.int)
        x = vec_alloc((num_words), np.int)
        i = 0
        with codecs.open(filename, encoding='utf-8', mode='r') as f:
            for line in f:
                sentence = line.split() + ['<EOS>']
                num_words += len(sentence)
                for w in sentence:
                    x[i] = words_vocab.get(w)
                    nch = min(len(w), maxw)
                    for k in range(nch):
                        xch[i,k] = chars_vocab.get(w[k], 0)
                    i += 1

        return x, xch
