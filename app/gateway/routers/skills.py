"""技能管理路由"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import List, Dict
import uuid
import os
from datetime import datetime

from app.gateway.schemas import SkillUploadRequest, SkillResponse
from app.gateway.exceptions import SkillNotFoundException

router = APIRouter()

# 简化的内存存储（生产环境应使用数据库）
_custom_skills = {}


@router.post("/custom", response_model=SkillResponse)
async def upload_custom_skill(request: SkillUploadRequest):
    """上传自定义技能"""
    skill_id = f"skill_{uuid.uuid4().hex[:12]}"

    # 验证文件
    if "SKILL.md" not in request.files:
        raise HTTPException(status_code=400, detail="SKILL.md 文件是必需的")

    # 创建技能目录
    skill_dir = f"skills/custom/{request.tenant_id}/{request.skill_name}"
    os.makedirs(skill_dir, exist_ok=True)

    # 保存文件
    for filename, content in request.files.items():
        filepath = os.path.join(skill_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    # 解析 SKILL.md 获取元数据
    import yaml
    skill_md = request.files.get("SKILL.md", "")
    metadata = {}
    if skill_md.startswith("---"):
        parts = skill_md.split("---", 2)
        if len(parts) >= 2:
            try:
                metadata = yaml.safe_load(parts[1]) or {}
            except:
                pass

    skill = {
        "skill_id": skill_id,
        "tenant_id": request.tenant_id,
        "name": request.skill_name,
        "description": request.description or metadata.get("description", ""),
        "triggers": request.triggers or metadata.get("triggers", []),
        "tags": request.tags or metadata.get("tags", []),
        "is_active": True,
        "created_at": datetime.utcnow().isoformat()
    }

    _custom_skills[skill_id] = skill

    return SkillResponse(**skill)


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str):
    """获取技能信息"""
    skill = _custom_skills.get(skill_id)
    if not skill:
        raise SkillNotFoundException(skill_id)
    return SkillResponse(**skill)


@router.get("/", response_model=List[SkillResponse])
async def list_skills(tenant_id: str = None):
    """列出所有技能"""
    skills = list(_custom_skills.values())
    if tenant_id:
        skills = [s for s in skills if s["tenant_id"] == tenant_id]
    return [SkillResponse(**s) for s in skills]


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str):
    """删除技能"""
    if skill_id in _custom_skills:
        skill = _custom_skills[skill_id]
        del _custom_skills[skill_id]

        # 删除文件
        import shutil
        skill_dir = f"skills/custom/{skill['tenant_id']}/{skill['name']}"
        if os.path.exists(skill_dir):
            shutil.rmtree(skill_dir)

        return {"deleted": True}
    raise SkillNotFoundException(skill_id)


@router.get("/builtin/list")
async def list_builtin_skills():
    """列出内置技能"""
    from utils.skill_loader import SkillRegistry

    registry = SkillRegistry.get_instance()
    try:
        skills = registry.get_all_skills()
        return {
            "skills": [
                {
                    "name": name,
                    "description": skill.description,
                    "triggers": skill.triggers,
                    "tags": skill.tags,
                    "execution_mode": skill.execution_mode
                }
                for name, skill in skills.items()
            ]
        }
    except RuntimeError:
        # Registry not initialized
        return {"skills": []}
