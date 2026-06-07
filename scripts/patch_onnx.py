import onnx, numpy as np
from onnx import helper, numpy_helper

model = onnx.load('/tmp/aiy_birds_V1.onnx')
g = model.graph

# Supprimer tout Reshape inséré par un patch précédent et récupérer le Gemm original
reshape_outs = {n.output[0]: n.input[0] for n in g.node if n.op_type == 'Reshape' and n.output and '_flat' in n.output[0]}
clean_nodes = [n for n in g.node if not (n.op_type == 'Reshape' and n.output and '_flat' in (n.output[0] if n.output else ''))]
del g.node[:]
g.node.extend(clean_nodes)
clean_inits = [i for i in g.initializer if i.name != '_reshape_shape']
del g.initializer[:]
g.initializer.extend(clean_inits)

gemm = next(n for n in g.node if n.op_type == 'Gemm')
attrs = {a.name: a for a in gemm.attribute}
trans_b = attrs['transB'].i if 'transB' in attrs else 0

# Remonter à l'input original (avant Reshape si déjà patché)
feat_input = gemm.input[0]
feat_input = reshape_outs.get(feat_input, feat_input)

weight_name = gemm.input[1]
bias_name   = gemm.input[2]
gemm_output = gemm.output[0]

print(f"transB={trans_b}  feat={feat_input}  weight={weight_name}  bias={bias_name}")

# Flatten l'entrée → [batch, 1280]
flat_name = feat_input + '_flat2d'
flatten = helper.make_node('Flatten', inputs=[feat_input], outputs=[flat_name], axis=1)

# Si transB=1 le poids est [N, K] → on transpose en [K, N] pour MatMul
if trans_b == 1:
    w_t_name = weight_name + '_T'
    transpose = helper.make_node('Transpose', inputs=[weight_name], outputs=[w_t_name], perm=[1, 0])
    matmul_b = w_t_name
else:
    transpose = None
    matmul_b = weight_name

mm_out = 'gemm_matmul_out'
matmul = helper.make_node('MatMul', inputs=[flat_name, matmul_b], outputs=[mm_out])
add    = helper.make_node('Add',    inputs=[mm_out, bias_name],    outputs=[gemm_output])

# Remplacer le Gemm
nodes = list(g.node)
idx   = nodes.index(gemm)
replacements = [flatten] + ([transpose] if transpose else []) + [matmul, add]
nodes = nodes[:idx] + replacements + nodes[idx+1:]
del g.node[:]
g.node.extend(nodes)

onnx.save(model, '/tmp/aiy_birds_V1.onnx')
size_mb = round(onnx.load('/tmp/aiy_birds_V1.onnx').ByteSize() / 1e6, 1)
print(f"Gemm → Flatten+MatMul+Add  ({size_mb} MB)")
