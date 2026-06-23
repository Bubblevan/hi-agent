import ast
import operator
import math
from typing import Dict, Any, List
from ..base import MyTool, ToolParameter

class CalculatorTool(MyTool):
    """简单的数学计算工具"""

    def __init__(self):
        super().__init__(
            name="calculator",
            description="执行基本的数学计算，支持 +, -, *, /, sqrt() 等"
        )
        self.operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
        }
        self.functions = {
            'sqrt': math.sqrt,
            'pi': math.pi,
        }

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="expression",
                type="string",
                description="数学表达式，例如 '2 + 3 * 4' 或 'sqrt(16)'",
                required=True
            )
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        """执行计算"""
        expression = parameters.get("expression", "")
        if not expression:
            return "错误: 表达式不能为空"

        try:
            node = ast.parse(expression, mode='eval')
            result = self._eval_node(node.body)
            return f"计算结果: {result}"
        except Exception as e:
            return f"计算失败: {str(e)}"

    def _eval_node(self, node):
        """递归求值 AST 节点"""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op = self.operators.get(type(node.op))
            if op:
                return op(left, right)
            raise ValueError(f"不支持的运算符: {type(node.op)}")
        elif isinstance(node, ast.Call):
            func_name = node.func.id
            if func_name in self.functions:
                args = [self._eval_node(arg) for arg in node.args]
                return self.functions[func_name](*args)
            raise ValueError(f"不支持的函数: {func_name}")
        elif isinstance(node, ast.Name):
            if node.id in self.functions:
                return self.functions[node.id]
            raise ValueError(f"未知变量: {node.id}")
        else:
            raise ValueError(f"不支持的表达式类型: {type(node)}")