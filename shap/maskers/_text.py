import numpy as np
import re
from ._masker import Masker
from ..utils import safe_isinstance
from ..utils.transformers import parse_prefix_suffix_for_tokenizer, SENTENCEPIECE_TOKENIZERS

class Text(Masker):
    """ This masks out tokens according to the given tokenizer.

    The masked variables are 
    
    output_type : "string" (default) or "token_ids"
        
    """
    def __init__(self, tokenizer, mask_token="auto", collapse_mask_token=False, output_type="string"):
        self.mask_history = {}
        self.tokenizer = tokenizer
        self.output_type = output_type
        self.collapse_mask_token = collapse_mask_token
        
        parsed_tokenizer_dict = parse_prefix_suffix_for_tokenizer(tokenizer)
        
        self.keep_prefix = parsed_tokenizer_dict['keep_prefix']
        self.keep_suffix = parsed_tokenizer_dict['keep_suffix']
        self.prefix_strlen = parsed_tokenizer_dict['prefix_strlen']
        self.suffix_strlen = parsed_tokenizer_dict['suffix_strlen']
        null_tokens = parsed_tokenizer_dict['null_tokens']

        if mask_token == "auto":
            if hasattr(self.tokenizer, "mask_token_id") and self.tokenizer.mask_token_id is not None:
                self.mask_token = " "+self.tokenizer.decode([self.tokenizer.mask_token_id])+" "#[self.prefix_strlen:-self.suffix_strlen]
                if self.keep_suffix > 0:
                    self.mask_token_id = tokenizer.encode(self.mask_token)[self.keep_prefix:-self.keep_suffix]
                else:
                    self.mask_token_id = tokenizer.encode(self.mask_token)[self.keep_prefix:]
            else:
                self.mask_token_id = None
                self.mask_token = ""
        elif mask_token == "":
            self.mask_token_id = None
            self.mask_token = ""
        else:
            self.mask_token = " "+mask_token+" "
            if self.keep_suffix > 0:
                self.mask_token_id = tokenizer.encode(self.mask_token)[self.keep_prefix:-self.keep_suffix]
            else:
                self.mask_token_id = tokenizer.encode(self.mask_token)[self.keep_prefix:]
        # assign mask token segment
        if self.keep_suffix > 0:
            self.mask_token_segment = self.token_segments(self.mask_token)[self.keep_prefix:-self.keep_suffix]
        else:
            self.mask_token_segment = self.token_segments(self.mask_token)[self.keep_prefix:]

        # note if this masker can use different background for different samples
        self.fixed_background = self.mask_token_id is None

        self.default_batch_size = 5

        self._s = None
    
    def __call__(self, mask, s):
        self._update_s_cache(s)

        # if we have a fixed prefix or suffix then we need to grow the mask to account for that
        if self.keep_prefix > 0 or self.keep_suffix > 0:
            mask = mask.copy()
            mask[:self.keep_prefix] = True
            mask[-self.keep_suffix:] = True
        

        if self.output_type == "string":
            if self.mask_token_id is None:
                out = self._segments_s[mask]
            else:
                #out = np.array([self._segments_s[i] if mask[i] else self.mask_token for i in range(len(mask))])
                out = []
                is_previous_appended_token_mask_token = False
                for i in range(len(mask)):
                    # TODO HACK!!! ignores mask for sep tokens
                    # check if sep_token exists?
                    if self._segments_s[i] == self.tokenizer.sep_token and i > 0 and i < len(self._segments_s) - 1 or mask[i]:
                        out.append(self._segments_s[i])
                        is_previous_appended_token_mask_token = False
                    else:
                        if self.collapse_mask_token and not is_previous_appended_token_mask_token:
                            out.extend(self.mask_token_segment)
                            is_previous_appended_token_mask_token = True
                        elif not self.collapse_mask_token:
                            out.extend(self.mask_token_segment)
                            is_previous_appended_token_mask_token = True
                out=np.array(out)

            if safe_isinstance(self.tokenizer, "transformers.tokenization_utils.PreTrainedTokenizer"):
                out = self.tokenizer.convert_tokens_to_string(out.tolist())
            elif safe_isinstance(self.tokenizer, "transformers.tokenization_utils_fast.PreTrainedTokenizerFast"):
                out = "".join(out)
        else:
            if self.mask_token_id is None:
                out = self._tokenized_s[mask]
            else:
                out = np.array([self._tokenized_s[i] if mask[i] else self.mask_token_id for i in range(len(mask))])

        # tokenizers which treat spaces like parts of the tokens and dont replace the special token while decoding need further postprocessing
        # by replacing whitespace encoded as '_' for sentencepiece tokenizer or 'Ġ' for sentencepiece like encoding (GPT2TokenizerFast)
        # with ' '
        if safe_isinstance(self.tokenizer, SENTENCEPIECE_TOKENIZERS):
            out = self.post_process_sentencepiece_tokenizer_output(out)
        # replace sequence of spaces with a single space and strip beginning and end spaces
        out = re.sub(r"[\s]+"," ",out).strip()
        out = re.sub("[\s]*" + self.tokenizer.sep_token + "[\s]*",self.tokenizer.sep_token,out) # TODO replace extra spaces around separator token
        return (np.array([out]),)

        if self.output_type == "string":
            decoded_str = self.tokenizer.decode(out)[self.prefix_strlen:][:-self.suffix_strlen].strip()
            
            if True:
                out2 = np.array(self.tokenizer.encode(decoded_str))
                if not np.all(out2 == out):
                    print(decoded_str)
                    print(self.tokenizer.decode(out))
                    print(out2)
                    print(out)
                    print(type(out2))
                    print(type(out))
                    print(out2.shape)
                    print(out.shape)
                    raise Exception("The string tokenizer is not symmetric?")
            return np.array([decoded_str])
        else:
            return np.array([out])
    
    def post_process_sentencepiece_tokenizer_output(self, s):
        # replaces whitespace encoded as '_' with ' ' for sentencepiece tokenizers
        s = s.replace('▁', ' ')
        return s

    def data_transform(self, s):
        if safe_isinstance(self.tokenizer, "transformers.tokenization_utils.PreTrainedTokenizer"):
            out = self.token_segments(s)
            out = [token+' ' for token in out]
            return out
        elif safe_isinstance(self.tokenizer, "transformers.tokenization_utils_fast.PreTrainedTokenizerFast"):
            return self.token_segments(s)
    
    def tokenize(self, s):
        if safe_isinstance(self.tokenizer, "transformers.tokenization_utils.PreTrainedTokenizer"):
            return self.tokenizer.encode_plus(s)
        elif safe_isinstance(self.tokenizer, "transformers.tokenization_utils_fast.PreTrainedTokenizerFast"):
            return self.tokenizer.encode_plus(s, return_offsets_mapping=True)
    
    def token_segments(self, s):
        if safe_isinstance(self.tokenizer, "transformers.tokenization_utils.PreTrainedTokenizer"):
            token_ids = self.tokenizer.encode_plus(s)['input_ids']
            tokens = self.tokenizer.convert_ids_to_tokens(token_ids)
            special_tokens_mask = self.tokenizer.get_special_tokens_mask(token_ids, already_has_special_tokens = True)
            # tokens = [tokens[i] if special_tokens_mask[i] == 0 else '' for i in range(len(special_tokens_mask))] 
            tokens = [tokens[i] if (i > 0 and i < len(tokens) - 1 or special_tokens_mask[i] == 0) else '' for i in range(len(special_tokens_mask))] # TODO possibly keep separator tokens inside
            return tokens

        elif safe_isinstance(self.tokenizer, "transformers.tokenization_utils_fast.PreTrainedTokenizerFast"):
            offsets_ = offsets = self.tokenizer.encode_plus(s, return_offsets_mapping=True) # ADDED
            offsets = self.tokenizer.encode_plus(s, return_offsets_mapping=True)["offset_mapping"]
            offsets = [(0,0) if o is None else o for o in offsets]
            s = ''.join(s) # TODO check if joining s with empty is allowed 
            # TODO bug with offsets mapping being reset to 0 index when we want it to continue off 1st sentence index; ignoring for now
            parts = [s[offsets[i][0]:max(offsets[i][1], offsets[i+1][0])] for i in range(len(offsets)-1)] 
            parts.append(s[offsets[len(offsets)-1][0]:offsets[len(offsets)-1][1]])
            return parts

    def clustering(self, s):
        self._update_s_cache(s)
        decoded_x = [self.tokenizer.decode([v]) for v in self._tokenized_s]
        pt = partition_tree(decoded_x)
        # self._mark_uninvertable(pt)
        return pt


    def _mark_uninvertable(self, clustering):
        """ This marks which clusters have non-invertable mappings through the tokenizer when masked.

        It seems like a bug that you can decode and then encode a set of token ids and not get what
        you started with...but this is possible with word endings in the transformers implementation
        of BERT for example. So here we mark such uninvertable clusters with negative values.
        """
    
        M = len(self._tokenized_s)
        assert len(clustering)+1 == M
        
        def recursive_mark(ind):
            if ind < M:
                return list(self._tokenized_s[ind:ind+1])
            else:
                lind = int(clustering[ind-M,0])
                rind = int(clustering[ind-M,1])
                ltokens = recursive_mark(lind)
                rtokens = recursive_mark(rind)
            
            # tmp = ltokens + [self.mask_token_id]
            tmp = ltokens + self.mask_token_id
            s2 = self.tokenizer.decode(tmp)
            e2 = self.tokenizer.encode(s2)
            if not np.all(e2[1:-1] == tmp):
                clustering[ind-M,2] = -1 # set the distance of this cluster negative so it can't be split
            
            # tmp = [self.mask_token_id] + rtokens
            tmp = self.mask_token_id + rtokens
            s2 = self.tokenizer.decode(tmp)
            e2 = self.tokenizer.encode(s2)
            if not np.all(e2[1:-1] == tmp):
                clustering[ind-M,2] = -1 # set the distance of this cluster negative so it can't be split
            
            return ltokens + rtokens
        
        recursive_mark(M+len(clustering)-1)

    def _update_s_cache(self, s):
        if self._s != s:
            self._s = s
            self._tokenized_s_full = self.tokenize(s)
            self._tokenized_s = np.array(self._tokenized_s_full.data["input_ids"])
            self._segments_s = np.array(self.token_segments(s))

    def shape(self, s):
        self._update_s_cache(s)
        return (1,len(self._tokenized_s))

    def mask_shapes(self, s):
        self._update_s_cache(s)
        return [(len(self._tokenized_s),)]

    def invariants(self, s):
        self._update_s_cache(s)

        invariants = np.zeros(len(self._tokenized_s), dtype=np.bool)
        if self.keep_prefix > 0:
            invariants[:self.keep_prefix] = True
        if self.keep_suffix > 0:
            invariants[-self.keep_suffix:] = True
        # ADDED: separator token
        for i in range(len(self._tokenized_s)):
            if self._tokenized_s[i] == self.tokenizer.sep_token_id: # TODO check if exists
                invariants[i] = True
        return invariants.reshape(1,-1)

    def feature_names(self, s):
        self._update_s_cache(s)
        return [[self.tokenizer.decode([v]) for v in self._tokenized_s]]


openers = {
    "(": ")"
}
closers = {
    ")": "("
}
enders = [".", ","]
connectors = ["but", "and", "or"]
separators = ["</s>"] # TODO added, need way to get separator tokens?

class Token():
    def __init__(self, value):
        self.s = value
        if value in openers or value in closers:
            self.balanced = False
        else:
            self.balanced = True
            
    def __str__(self):
        return self.s
    
    def __repr__(self):
        if not self.balanced:
            return self.s + "!"
        return self.s
    
class TokenGroup():
    def __init__(self, group, index=None):
        self.g = group
        self.index = index
    
    def __repr__(self):
        return self.g.__repr__()
    
    def __getitem__(self, index):
        return self.g[index]
    
    def __add__(self, o):
        return TokenGroup(self.g + o.g)
    
    def __len__(self):
        return len(self.g)

def merge_score(group1, group2):
    score = 0
    # TODO check that this ensures sep tokens are combined last
    if group1[-1].s in separators and group2[0].s in separators:
        score -= 10000000000

    # merge broken-up parts of words first
    if group2[0].s.startswith("##"):
        score += 20
        
    # merge apostrophe endings next
    if group2[0].s == "'" and (len(group2) == 1 or (len(group2) == 2 and group2[1].s in ["t", "s"])):
        score += 15
    if group1[-1].s == "'" and group2[0].s in ["t", "s"]:
        score += 15
    
    start_ctrl = group1[0].s.startswith("[") and group1[0].s.endswith("]")
    end_ctrl = group2[-1].s.startswith("[") and group2[-1].s.endswith("]")

    if (start_ctrl and not end_ctrl) or (end_ctrl and not start_ctrl):
        score -= 1000
    if group2[0].s in openers and not group2[0].balanced:
        score -= 100
    if group1[-1].s in closers and not group1[-1].balanced:
        score -= 100
    
    # attach surrounding an openers and closers a bit later
    if group1[0].s in openers and not group2[-1] in closers:
        score -= 2
    
    # reach across connectors later
    if group1[-1].s in connectors or group2[0].s in connectors:
        score -= 2
        
    # reach across commas later
    if group1[-1].s == ",":
        score -= 10
    if group2[0].s == ",":
        if len(group2) > 1: # reach across
            score -= 10
        else:
            score -= 1
        
    # reach across sentence endings later
    if group1[-1].s in [".", "?", "!"]:
        score -= 20
    if group2[0].s in [".", "?", "!"]:
        if len(group2) > 1: # reach across
            score -= 20
        else:
            score -= 1
    
    score -= len(group1) + len(group2)
    #print(group1, group2, score)
    return score
    
def merge_closest_groups(groups):
    scores = [merge_score(groups[i], groups[i+1]) for i in range(len(groups)-1)]
    #print(scores)
    ind = np.argmax(scores)
    groups[ind] = groups[ind] + groups[ind+1]
    #print(groups[ind][0].s in openers, groups[ind][0])
    if groups[ind][0].s in openers and groups[ind+1][-1].s == openers[groups[ind][0].s]:
        groups[ind][0].balanced = True
        groups[ind+1][-1].balanced = True
        
    
    groups.pop(ind+1)    
    
def partition_tree(decoded_tokens):
    token_groups = [TokenGroup([Token(t)], i) for i,t in enumerate(decoded_tokens)]
#     print(token_groups)
    M = len(decoded_tokens)
    new_index = M
    clustm = np.zeros((M-1, 4))
    for i in range(len(token_groups)-1):
        scores = [merge_score(token_groups[i], token_groups[i+1]) for i in range(len(token_groups)-1)]
#         print(scores)
        ind = np.argmax(scores)

        lind = token_groups[ind].index
        rind = token_groups[ind+1].index
        clustm[new_index-M,0] = token_groups[ind].index
        clustm[new_index-M,1] = token_groups[ind+1].index
        clustm[new_index-M,2] = -scores[ind]
        clustm[new_index-M,3] = (clustm[lind-M,3] if lind >= M else 1) + (clustm[rind-M,3] if rind >= M else 1)

        token_groups[ind] = token_groups[ind] + token_groups[ind+1]
        token_groups[ind].index = new_index

        # track balancing of openers/closers
        if token_groups[ind][0].s in openers and token_groups[ind+1][-1].s == openers[token_groups[ind][0].s]:
            token_groups[ind][0].balanced = True
            token_groups[ind+1][-1].balanced = True

        token_groups.pop(ind+1)
        new_index += 1

    # negative means we should never split a group, so we add 10 to ensure these are very tight groups
    # (such as parts of the same word)
    clustm[:,2] = clustm[:,2] + 10

    return clustm