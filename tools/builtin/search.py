# tools/builtin/search.py
import os
from typing import Dict, Any, List, Optional
from ..base import MyTool, ToolParameter

class SearchTool(MyTool):
    """
    智能搜索工具，支持 Tavily 和 SerpApi 两种后端。
    自动选择可用后端，优先 Tavily。
    """

    def __init__(self, backend: str = "hybrid"):
        """
        :param backend: "hybrid" 自动选择，或 "tavily" / "serpapi" 强制指定
        """
        super().__init__(
            name="search",
            description="搜索互联网获取实时信息，支持智能选择搜索源。"
        )
        self.backend = backend
        self.tavily_key = os.getenv("TAVILY_API_KEY")
        self.serpapi_key = os.getenv("SERPAPI_API_KEY")
        self.available_backends = []
        self._setup_backends()

    def _setup_backends(self):
        """检测可用的搜索后端"""
        # 检查 Tavily
        if self.tavily_key:
            try:
                from tavily import TavilyClient
                self.tavily_client = TavilyClient(api_key=self.tavily_key)
                self.available_backends.append("tavily")
                print("Tavily 搜索源已启用")
            except ImportError:
                print("Tavily 库未安装，请运行: pip install tavily-python")
            except Exception as e:
                print(f"Tavily 初始化失败: {e}")

        # 检查 SerpApi
        if self.serpapi_key:
            try:
                import serpapi
                self.serpapi_module = serpapi
                self.available_backends.append("serpapi")
                print("SerpApi 搜索源已启用")
            except ImportError:
                print("SerpApi 库未安装，请运行: pip install serpapi")
            except Exception as e:
                print(f"SerpApi 初始化失败: {e}")

        if not self.available_backends:
            print("没有可用的搜索源，请配置 TAVILY_API_KEY 或 SERPAPI_API_KEY 环境变量")

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="搜索查询词",
                required=True
            )
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        """执行搜索"""
        query = parameters.get("query", "").strip()
        if not query:
            return "错误: 搜索查询不能为空"

        if not self.available_backends:
            return """没有可用的搜索源，请配置以下 API 密钥之一:
- TAVILY_API_KEY (获取: https://tavily.com/)
- SERPAPI_API_KEY (获取: https://serpapi.com/)
然后重启程序。"""

        print(f"开始搜索: {query}")

        # 根据后端模式执行搜索
        if self.backend == "hybrid":
            return self._search_hybrid(query)
        elif self.backend == "tavily":
            return self._search_tavily(query)
        elif self.backend == "serpapi":
            return self._search_serpapi(query)
        else:
            return f"未知后端: {self.backend}，请使用 hybrid / tavily / serpapi"

    def _search_hybrid(self, query: str) -> str:
        """混合搜索：优先 Tavily，失败则 SerpApi"""
        if "tavily" in self.available_backends:
            try:
                return self._search_tavily(query)
            except Exception as e:
                print(f"Tavily 搜索失败: {e}")
                if "serpapi" in self.available_backends:
                    print("切换到 SerpApi")
                    return self._search_serpapi(query)
                else:
                    return f"Tavily 搜索失败且无备用后端: {e}"

        elif "serpapi" in self.available_backends:
            try:
                return self._search_serpapi(query)
            except Exception as e:
                return f"SerpApi 搜索失败: {e}"

        return "没有可用的搜索后端"

    def _search_tavily(self, query: str) -> str:
        """使用 Tavily 搜索"""
        response = self.tavily_client.search(
            query=query,
            search_depth="basic",
            include_answer=True,
            max_results=3
        )

        result = f"Tavily AI 搜索结果:\n"
        if response.get("answer"):
            result += f"直接答案: {response['answer']}\n\n"

        result += "相关结果:\n"
        for i, item in enumerate(response.get("results", [])[:3], 1):
            title = item.get("title", "无标题")
            content = item.get("content", "")[:200]
            url = item.get("url", "")
            result += f"[{i}] {title}\n"
            result += f"    {content}...\n"
            result += f"    来源: {url}\n\n"

        return result

    def _search_serpapi(self, query: str) -> str:
        """使用 SerpApi 搜索"""
        search = self.serpapi_module.GoogleSearch({
            "q": query,
            "api_key": self.serpapi_key,
            "num": 3
        })
        results = search.get_dict()

        result = "Google 搜索结果:\n"
        if "organic_results" in results:
            for i, item in enumerate(results["organic_results"][:3], 1):
                title = item.get("title", "无标题")
                snippet = item.get("snippet", "")
                link = item.get("link", "")
                result += f"[{i}] {title}\n"
                result += f"    {snippet}\n"
                result += f"    链接: {link}\n\n"
        else:
            result += "未找到相关结果。\n"

        return result