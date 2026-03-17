"""
CLI 엔트리포인트. 로컬에서 대화형으로 에이전트를 테스트할 때 사용.

Usage:
    uv run python main.py
"""

from dotenv import load_dotenv

load_dotenv()

from src.agent.product_agent import create_product_agent


def main():
    agent = create_product_agent()

    print("=" * 60)
    print("어스플러스 상품 세팅 에이전트 (POC)")
    print("=" * 60)
    print("상품 세팅을 시작하려면 마스터 이름이나 요청을 입력하세요.")
    print("종료: Ctrl+C 또는 'quit'\n")

    while True:
        try:
            user_input = input(">> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                print("종료합니다.")
                break

            response = agent(user_input)
            print()

        except KeyboardInterrupt:
            print("\n종료합니다.")
            break
        except Exception as e:
            print(f"\n오류 발생: {e}\n")


if __name__ == "__main__":
    main()
