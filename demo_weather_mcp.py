import asyncio
import httpx
from mcp.server.fastmcp import FastMCP

# 1. 创建一个名为 weather 的 MCP Server
mcp = FastMCP("weather")

# 2. 使用 @mcp.tool() 装饰器将普通 Python 函数注册为 MCP 工具
@mcp.tool()
async def get_weather(location: str) -> str:
    """获取指定城市的天气信息。例如：Shanghai, New York, London"""
    async with httpx.AsyncClient() as client:
        # 这里使用 wttr.in 免费天气接口作为演示
        response = await client.get(f"https://wttr.in/{location}?format=3")
        return response.text

if __name__ == "__main__":
    # 3. 使用 stdio 模式运行，这是本地 MCP Server 最常用的通信方式
    # nanobot 会通过标准输入输出与这个 Server 进行 JSON-RPC 通信
    mcp.run(transport='stdio')
