"""Dependency-light characterization, not full ComfyUI integration testing.

Compile unchanged AST function bodies from the real before/after modules.
Tensor substitutes expose shape only. No imports, model weights or GPUs needed.
"""
import ast
import copy
import itertools
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent


def load(variant):
    path = ROOT / variant / 'comfy/model_detection.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'count_blocks', 'any_suffix_in', 'detect_unet_config',
             '_detect_mmdit_config', '_detect_cascade_config'}
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = {'math': math}
    exec(compile(tree, str(path), 'exec'), namespace)
    return namespace


def weight(*shape):
    return SimpleNamespace(shape=shape)


class QualityDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = load('before')
        cls.after = load('after')

    def compare(self, values, prefix):
        original = copy.deepcopy(values)
        expected = self.before['detect_unet_config'](values, prefix)
        actual = self.after['detect_unet_config'](values, prefix)
        self.assertEqual(expected, actual)
        self.assertEqual(values, original)
        return actual

    def test_mmdit_optional_combinations(self):
        optional = [
            ('final_layer.linear.weight', weight(64, 128)),
            ('y_embedder.mlp.0.weight', weight(128, 32)),
            ('context_embedder.weight', weight(128, 64)),
            ('pos_embed', weight(1, 256, 128)),
            ('joint_blocks.0.context_block.attn.ln_q.weight', weight(64)),
            ('context_processor.layers.0.attn.qkv.weight', weight(1)),
            ('joint_blocks.2.x_block.attn2.qkv.weight', weight(1)),
        ]
        for prefix, enabled in itertools.product(['', 'model.'], itertools.product([False, True], repeat=7)):
            with self.subTest(prefix=prefix, enabled=enabled):
                values = {prefix + 'joint_blocks.0.context_block.attn.qkv.weight': weight(1),
                          prefix + 'x_embedder.proj.weight': weight(128, 16, 2, 2)}
                values.update({prefix + key: value for (key, value), use in zip(optional, enabled) if use})
                actual = self.compare(values, prefix)
                self.assertEqual(actual['depth'], 2)
                self.assertEqual(actual['patch_size'], 2)

    def test_cascade_variants(self):
        cases = [({}, {}),
                 ({'clip_txt_mapper.weight': weight(1536)}, {'stable_cascade_stage': 'c', 'c_cond': 1536}),
                 ({'clip_txt_mapper.weight': weight(2048)}, {'stable_cascade_stage': 'c', 'c_cond': 2048}),
                 ({'clip_txt_mapper.weight': weight(777)}, {'stable_cascade_stage': 'c'}),
                 *[({'clip_mapper.weight': weight(1), 'down_blocks.1.0.channelwise.0.weight': weight(1, width)},
                    {'stable_cascade_stage': 'b'}) for width in [640, 576, 777]],
                 ({'clip_txt_mapper.weight': weight(2048), 'clip_mapper.weight': weight(1)},
                  {'stable_cascade_stage': 'c', 'c_cond': 2048})]
        for prefix, (fields, expected) in itertools.product(['', 'model.'], cases):
            with self.subTest(prefix=prefix, fields=fields):
                values = {prefix + 'clf.1.weight': weight(1)}
                values.update({prefix + key: value for key, value in fields.items()})
                actual = self.compare(values, prefix)
                self.assertTrue(expected.items() <= actual.items())
                if not fields:
                    self.assertEqual(actual, {})

    def test_precedence(self):
        values = {'joint_blocks.0.context_block.attn.qkv.weight': weight(1),
                  'x_embedder.proj.weight': weight(128, 16, 2, 2), 'clf.1.weight': weight(1)}
        self.assertIn('patch_size', self.compare(values, ''))
        values.update({key: weight(1) for key in ['cond_layer_logits', 'latent_conditioners.0.weight',
                       'diffusion_transformer.transformer.layers.0.self_attn.to_qkv.weight']})
        self.assertEqual(self.compare(values, ''), {'audio_model': 'minimax_music3'})

    def test_missing_required_key_preserves_error(self):
        for namespace in [self.before, self.after]:
            with self.assertRaises(KeyError):
                namespace['detect_unet_config']({'joint_blocks.0.context_block.attn.qkv.weight': weight(1)}, '')

    def test_suffix_contract(self):
        for namespace in [self.before, self.after]:
            fn = namespace['any_suffix_in']
            self.assertFalse(fn({'pre.main.x'}, 'pre.', 'main'))
            self.assertTrue(fn({'pre.main.x'}, 'pre.', 'main', ['.x']))
            self.assertFalse(fn({'pre.main.x'}, 'pre.', 'main', ('.y',)))
            self.assertTrue(fn({'pre.main.x'}, 'pre.', 'main', ('.y', '.x')))
            self.assertFalse(fn({'pre.main.x'}, 'pre.', 'main'))

    def test_remaining_dispatch_body_is_unchanged(self):
        def function(variant):
            tree = ast.parse((ROOT / variant / 'comfy/model_detection.py').read_text(encoding='utf-8'))
            return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'detect_unet_config')
        before, after = function('before'), function('after')
        # Only the two selected branch bodies are allowed to change.
        for node in before.body:
            if isinstance(node, ast.If) and any(signature in ast.unparse(node.test) for signature in
                    ['joint_blocks.0.context_block.attn.qkv.weight', 'clf.1.weight']):
                matching = next(n for n in after.body if isinstance(n, ast.If)
                                and ast.dump(n.test) == ast.dump(node.test))
                node.body = matching.body
        self.assertEqual(ast.dump(before), ast.dump(after))


if __name__ == '__main__':
    unittest.main()
